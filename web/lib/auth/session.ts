/**
 * Session checks shared by Proxy (`proxy.ts`), the API proxy route handler and server components.
 * Server only; reads env at call time.
 */
import { readAuthConfig, SESSION_COOKIE, type AuthConfig } from "./config";
import { verifySession } from "./token";

export type AuthState =
  | { status: "ok"; user: string }
  | { status: "disabled" }
  | { status: "unauthenticated" }
  | { status: "misconfigured" };

export async function authStateFromToken(token: string | undefined, config: AuthConfig = readAuthConfig()): Promise<AuthState> {
  if (config.mode === "disabled") return { status: "disabled" };
  if (config.mode === "misconfigured") return { status: "misconfigured" };
  const payload = await verifySession(token, config.secret, { expectedUser: config.user });
  return payload ? { status: "ok", user: payload.sub } : { status: "unauthenticated" };
}

/** Reads the cookie from a raw Request (route handlers, Proxy). */
export function sessionTokenFromRequest(req: Request): string | undefined {
  const header = req.headers.get("cookie");
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === SESSION_COOKIE) return part.slice(eq + 1).trim();
  }
  return undefined;
}

export function isAllowed(state: AuthState): state is { status: "ok"; user: string } | { status: "disabled" } {
  return state.status === "ok" || state.status === "disabled";
}

export const UNAUTHENTICATED_HEADER = "x-patribot-auth";

/** 401/503 JSON for API requests without a valid session. */
export function apiAuthError(state: AuthState): Response {
  if (state.status === "misconfigured") {
    return Response.json(
      { detail: "Sign-in is not configured on this deployment." },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
  return Response.json(
    { detail: "Not signed in." },
    { status: 401, headers: { "cache-control": "no-store", [UNAUTHENTICATED_HEADER]: "required" } },
  );
}
