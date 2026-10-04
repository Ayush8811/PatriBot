/**
 * Server-side proxy to the FastAPI backend. The browser only ever talks to `/api/proxy/*` on our own origin; this
 * handler checks the session, then forwards to `${PATRIBOT_API_URL}/api/v1/<path>` with the `x-patribot-key`
 * header. Both env vars are server-only, so the backend URL and key never reach the client bundle.
 *
 * - GET and POST, status codes passed through, bodies streamed through (so `POST /chat` SSE works).
 * - A generous upstream timeout: the free API host sleeps and can take 30–60 s to wake.
 * - An upstream 401/403 means *our* key was rejected (a deployment problem, not the viewer's session), so it is
 *   reported as 502; a 401 from this handler always means "not signed in".
 */
import { readAuthConfig } from "@/lib/auth/config";
import { apiAuthError, authStateFromToken, isAllowed, sessionTokenFromRequest } from "@/lib/auth/session";

export const UPSTREAM_TIMEOUT_MS = 90_000;
const MAX_BODY_BYTES = 64 * 1024;
const SEGMENT = /^[A-Za-z0-9._~-]+$/;

export interface ProxyDeps {
  fetchImpl?: typeof fetch;
  env?: Record<string, string | undefined>;
  timeoutMs?: number;
}

function json(status: number, detail: string): Response {
  return Response.json({ detail }, { status, headers: { "cache-control": "no-store" } });
}

/** `https://host/` or `https://host/api/v1` → `https://host` */
export function apiOrigin(raw: string | undefined): string | null {
  const v = (raw ?? "").trim().replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  if (!v) return null;
  try {
    const u = new URL(v);
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    return `${u.origin}${u.pathname.replace(/\/+$/, "")}`;
  } catch {
    return null;
  }
}

export async function proxyToApi(req: Request, segments: string[], deps: ProxyDeps = {}): Promise<Response> {
  const env = deps.env ?? process.env;
  const state = await authStateFromToken(sessionTokenFromRequest(req), readAuthConfig(env));
  if (!isAllowed(state)) return apiAuthError(state);

  if (req.method !== "GET" && req.method !== "POST") return json(405, "Method not allowed.");
  // Only plain path segments: no "..", no encoded slashes, nothing that could escape /api/v1.
  if (segments.length === 0 || segments.some((s) => !SEGMENT.test(s) || s === "." || s === "..")) {
    return json(400, "Bad API path.");
  }

  const origin = apiOrigin(env.PATRIBOT_API_URL);
  const key = env.PATRIBOT_API_KEY ?? "";
  if (!origin || !key) return json(503, "The PatriBot API is not configured on this deployment.");

  const target = `${origin}/api/v1/${segments.join("/")}${new URL(req.url).search}`;
  const headers = new Headers({ "x-patribot-key": key, accept: req.headers.get("accept") ?? "application/json" });
  let body: string | undefined;
  if (req.method === "POST") {
    body = await req.text();
    if (body.length > MAX_BODY_BYTES) return json(413, "Request body too large.");
    headers.set("content-type", req.headers.get("content-type") ?? "application/json");
  }

  const timeoutMs = deps.timeoutMs ?? UPSTREAM_TIMEOUT_MS;
  // The timeout covers waiting for the response headers (cold start); once they arrive it is cleared so a long
  // stream is not cut off. The viewer navigating away (req.signal) aborts the upstream call too.
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), timeoutMs);
  const signal = AbortSignal.any([timeout.signal, req.signal]);
  let upstream: Response;
  try {
    upstream = await (deps.fetchImpl ?? fetch)(target, { method: req.method, headers, body, signal, cache: "no-store", redirect: "manual" });
  } catch {
    if (timeout.signal.aborted) {
      return json(504, `The PatriBot API did not answer within ${Math.round(timeoutMs / 1000)} s. It may still be waking up; try again.`);
    }
    if (req.signal.aborted) return new Response(null, { status: 499 });
    return json(502, "Could not reach the PatriBot API.");
  } finally {
    clearTimeout(timer);
  }

  if (upstream.status === 401 || upstream.status === 403) {
    await upstream.body?.cancel().catch(() => {});
    return json(502, "The PatriBot API rejected this app's key (check PATRIBOT_API_KEY on both sides).");
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    await upstream.body?.cancel().catch(() => {});
    return json(502, "Unexpected redirect from the PatriBot API.");
  }

  const out = new Headers({ "cache-control": "no-store" });
  const ct = upstream.headers.get("content-type");
  if (ct) out.set("content-type", ct);
  if (ct?.startsWith("text/event-stream")) {
    out.set("cache-control", "no-cache, no-transform");
    out.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}
