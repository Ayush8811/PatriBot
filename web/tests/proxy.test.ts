// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_COOKIE } from "@/lib/auth/config";
import { signSession } from "@/lib/auth/token";
import { apiOrigin, proxyToApi } from "@/lib/api/proxy-handler";
import { proxy } from "@/proxy";

const SECRET = "test-session-secret-that-is-long-enough-0123456789";
const ENV = {
  PATRIBOT_AUTH_USER: "owner",
  PATRIBOT_AUTH_PASSWORD_HASH: "scrypt$1024$8$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA==",
  PATRIBOT_SESSION_SECRET: SECRET,
  PATRIBOT_API_URL: "https://api.example.test/",
  PATRIBOT_API_KEY: "k-test-123",
  NODE_ENV: "production",
};

async function cookieHeader(user = "owner", secret = SECRET) {
  return `theme=dark; ${SESSION_COOKIE}=${await signSession(user, secret)}`;
}

function req(path: string, init: RequestInit = {}) {
  return new Request(`http://localhost:3000/api/proxy/${path}`, init);
}

describe("API proxy route handler", () => {
  it("rejects requests without a session (401, upstream never called)", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const res = await proxyToApi(req("health"), ["health"], { env: ENV, fetchImpl });
    expect(res.status).toBe(401);
    expect(res.headers.get("x-patribot-auth")).toBe("required");
    expect(await res.json()).toEqual({ detail: "Not signed in." });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a forged, foreign-user or wrong-secret cookie", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    for (const cookie of [
      `${SESSION_COOKIE}=abc.def`,
      await cookieHeader("mallory"),
      await cookieHeader("owner", `${SECRET}-other`),
    ]) {
      const res = await proxyToApi(req("health", { headers: { cookie } }), ["health"], { env: ENV, fetchImpl });
      expect(res.status).toBe(401);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("fails closed with 503 when auth env is missing", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const res = await proxyToApi(req("health", { headers: { cookie: await cookieHeader() } }), ["health"], {
      env: { NODE_ENV: "production", PATRIBOT_API_URL: ENV.PATRIBOT_API_URL, PATRIBOT_API_KEY: "k" },
      fetchImpl,
    });
    expect(res.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("forwards GET with the API key and passes status and body through", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      Response.json({ detail: "unknown place" }, { status: 404, headers: { "set-cookie": "x=1" } }),
    );
    const res = await proxyToApi(
      req("places/search?q=kolk&limit=10", { headers: { cookie: await cookieHeader(), authorization: "Bearer leak" } }),
      ["places", "search"],
      { env: ENV, fetchImpl },
    );
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "unknown place" });
    expect(res.headers.get("set-cookie")).toBeNull();
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.test/api/v1/places/search?q=kolk&limit=10");
    const h = new Headers(init!.headers);
    expect(h.get("x-patribot-key")).toBe("k-test-123");
    expect(h.get("cookie")).toBeNull();
    expect(h.get("authorization")).toBeNull();
    expect(init!.method).toBe("GET");
  });

  it("forwards POST bodies and streams SSE through", async () => {
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('event: token\ndata: {"text":"Hi"}\n\n'));
        c.enqueue(enc.encode('event: done\ndata: {"usage":{"queries_left_today":2}}\n\n'));
        c.close();
      },
    });
    const fetchImpl = vi.fn<typeof fetch>(
      async () => new Response(stream, { status: 200, headers: { "content-type": "text/event-stream; charset=utf-8" } }),
    );
    const body = JSON.stringify({ message: "hi" });
    const res = await proxyToApi(
      req("chat", { method: "POST", body, headers: { cookie: await cookieHeader(), "content-type": "application/json" } }),
      ["chat"],
      { env: ENV, fetchImpl },
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(res.headers.get("cache-control")).toContain("no-transform");
    expect(await res.text()).toContain("queries_left_today");
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.test/api/v1/chat");
    expect(init!.method).toBe("POST");
    expect(init!.body).toBe(body);
  });

  it("rejects path tricks and other methods", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const cookie = await cookieHeader();
    for (const segs of [["..", "admin"], ["a/b"], ["%2e%2e"], []]) {
      const res = await proxyToApi(req("x", { headers: { cookie } }), segs, { env: ENV, fetchImpl });
      expect(res.status).toBe(400);
    }
    const del = await proxyToApi(req("plan", { method: "DELETE", headers: { cookie } }), ["plan"], { env: ENV, fetchImpl });
    expect(del.status).toBe(405);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps an upstream key rejection to 502, not 401", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => Response.json({ detail: "bad key" }, { status: 401 }));
    const res = await proxyToApi(req("health", { headers: { cookie: await cookieHeader() } }), ["health"], { env: ENV, fetchImpl });
    expect(res.status).toBe(502);
    expect(res.headers.get("x-patribot-auth")).toBeNull();
  });

  it("returns 504 with a friendly message when the API is still waking up", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init!.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const res = await proxyToApi(req("health", { headers: { cookie: await cookieHeader() } }), ["health"], {
      env: ENV,
      fetchImpl,
      timeoutMs: 20,
    });
    expect(res.status).toBe(504);
    expect((await res.json()).detail).toMatch(/waking up/);
  });

  it("returns 503 when the API URL or key is not configured", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const res = await proxyToApi(req("health", { headers: { cookie: await cookieHeader() } }), ["health"], {
      env: { ...ENV, PATRIBOT_API_KEY: "" },
      fetchImpl,
    });
    expect(res.status).toBe(503);
  });

  it("normalises PATRIBOT_API_URL", () => {
    expect(apiOrigin("https://x.onrender.com")).toBe("https://x.onrender.com");
    expect(apiOrigin("https://x.onrender.com/api/v1/")).toBe("https://x.onrender.com");
    expect(apiOrigin("ftp://x")).toBeNull();
    expect(apiOrigin("")).toBeNull();
  });
});

describe("proxy.ts auth gate", () => {
  const saved = { ...process.env };
  beforeEach(() => {
    Object.assign(process.env, ENV);
    delete process.env.PATRIBOT_AUTH_DISABLED;
  });
  afterEach(() => {
    process.env = { ...saved };
  });

  const nreq = (path: string, init: { method?: string; cookie?: string } = {}) =>
    new NextRequest(`http://localhost:3000${path}`, {
      method: init.method ?? "GET",
      headers: init.cookie ? { cookie: init.cookie } : {},
    });

  it("redirects pages to /login with a safe next", async () => {
    const res = await proxy(nreq("/plan?origin=KOLKATA&destination=DELHI"));
    expect(res.status).toBe(307);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.pathname).toBe("/login");
    expect(loc.searchParams.get("next")).toBe("/plan?origin=KOLKATA&destination=DELHI");
  });

  it("answers API calls with 401 JSON", async () => {
    const res = await proxy(nreq("/api/proxy/health"));
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ detail: "Not signed in." });
  });

  it("lets /login through and lets a valid session through everywhere", async () => {
    expect((await proxy(nreq("/login"))).headers.get("x-middleware-next")).toBe("1");
    const cookie = await cookieHeader();
    expect((await proxy(nreq("/plan", { cookie }))).headers.get("x-middleware-next")).toBe("1");
    expect((await proxy(nreq("/api/proxy/health", { cookie }))).headers.get("x-middleware-next")).toBe("1");
  });

  it("sends a signed-in visitor from /login to next (same-origin only)", async () => {
    const cookie = await cookieHeader();
    const ok = await proxy(nreq("/login?next=%2Ftrains%2F12301", { cookie }));
    expect(new URL(ok.headers.get("location")!).pathname).toBe("/trains/12301");
    const evil = await proxy(nreq("/login?next=https%3A%2F%2Fevil.example", { cookie }));
    expect(new URL(evil.headers.get("location")!).href).toBe("http://localhost:3000/");
  });

  it("fails closed when auth is not configured", async () => {
    delete process.env.PATRIBOT_SESSION_SECRET;
    process.env.PATRIBOT_AUTH_DISABLED = "1"; // ignored outside mock/dev
    const page = await proxy(nreq("/", { cookie: await cookieHeader() }));
    expect(page.status).toBe(307);
    const api = await proxy(nreq("/api/proxy/health"));
    expect(api.status).toBe(503);
  });
});
