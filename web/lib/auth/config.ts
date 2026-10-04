/**
 * Server-side auth configuration, read from server-only env vars at request time (never NEXT_PUBLIC_*):
 *   PATRIBOT_AUTH_USER            the one username
 *   PATRIBOT_AUTH_PASSWORD_HASH   scrypt$N$r$p$salt$hash (npm run hash-password)
 *   PATRIBOT_SESSION_SECRET       ≥ 32 chars, signs the session cookie
 *   PATRIBOT_AUTH_DISABLED=1      local dev/tests only: honoured only in mock mode or `next dev`
 *
 * Fails closed: if anything is missing or malformed the app is "misconfigured" and nobody gets in.
 */
import { API_MOCK } from "@/lib/config";

import { MIN_SECRET_LENGTH } from "./token";

export const SESSION_COOKIE = "patribot_session";

export type AuthConfig =
  | { mode: "enabled"; user: string; passwordHash: string; secret: string }
  | { mode: "disabled" }
  | { mode: "misconfigured"; problems: string[] };

const HASH_SHAPE = /^scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/;

export function readAuthConfig(env: Record<string, string | undefined> = process.env): AuthConfig {
  // Mock mode is decided at build time (NEXT_PUBLIC_* is inlined), so fall back to the inlined flag.
  const mock = (env.NEXT_PUBLIC_API_MOCK ?? (API_MOCK ? "1" : "0")) === "1";
  const devOrMock = mock || env.NODE_ENV === "development";
  if (env.PATRIBOT_AUTH_DISABLED === "1" && devOrMock) return { mode: "disabled" };

  const user = (env.PATRIBOT_AUTH_USER ?? "").trim();
  const passwordHash = (env.PATRIBOT_AUTH_PASSWORD_HASH ?? "").trim();
  const secret = env.PATRIBOT_SESSION_SECRET ?? "";
  const problems: string[] = [];
  if (!user) problems.push("PATRIBOT_AUTH_USER is not set");
  if (!passwordHash) problems.push("PATRIBOT_AUTH_PASSWORD_HASH is not set");
  else if (!HASH_SHAPE.test(passwordHash)) problems.push("PATRIBOT_AUTH_PASSWORD_HASH is not a scrypt$… hash (in .env files escape every $ as \\$)");
  if (!secret) problems.push("PATRIBOT_SESSION_SECRET is not set");
  else if (secret.length < MIN_SECRET_LENGTH) problems.push(`PATRIBOT_SESSION_SECRET is shorter than ${MIN_SECRET_LENGTH} characters`);
  // PATRIBOT_AUTH_DISABLED=1 outside mock/dev is ignored: auth stays on (or the app stays locked).
  if (problems.length > 0) return { mode: "misconfigured", problems };
  return { mode: "enabled", user, passwordHash, secret };
}

/** Cookie attributes. `Secure` in production (Vercel is HTTPS); browsers treat localhost as secure too. */
export function sessionCookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: maxAgeSeconds,
    priority: "high" as const,
  };
}
