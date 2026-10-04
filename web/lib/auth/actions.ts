"use server";

/**
 * Server Functions for signing in and out. Both are deliberately public (anyone can POST them): `login` is the
 * auth check itself and `logout` only clears the caller's own cookie. Next.js checks the Origin header of Server
 * Function calls against the host, which covers CSRF.
 */
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { readAuthConfig, SESSION_COOKIE, sessionCookieOptions } from "./config";
import { safeNextPath } from "./next-param";
import { safeEqualString, verifyPassword } from "./password";
import { clientIp, loginLimiter } from "./rate-limit";
import { SESSION_TTL_SECONDS, signSession } from "./token";

export interface LoginState {
  error?: string;
  /** echoed back so the form keeps the username after a failed attempt */
  username?: string;
}

/** Fixed delay on every failed attempt (slows guessing; same for wrong user and wrong password). */
const FAILURE_DELAY_MS = 800;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function field(form: FormData, name: string, max: number): string {
  const v = form.get(name);
  return typeof v === "string" ? v.slice(0, max) : "";
}

export async function login(_prev: LoginState | undefined, form: FormData): Promise<LoginState> {
  const next = safeNextPath(field(form, "next", 2048));
  const config = readAuthConfig();
  if (config.mode === "disabled") redirect(next);
  if (config.mode === "misconfigured") {
    return { error: "Sign-in is not configured on this deployment. Set the PATRIBOT_AUTH_* env vars." };
  }

  const username = field(form, "username", 256).trim();
  const password = field(form, "password", 1024);
  const ip = clientIp(await headers());

  const wait = loginLimiter.retryAfterMs(ip);
  if (wait > 0) {
    await sleep(FAILURE_DELAY_MS);
    return { username, error: `Too many failed attempts. Try again in ${Math.ceil(wait / 60_000)} min.` };
  }

  // Always run both checks so timing doesn't reveal whether the username was right.
  const userOk = safeEqualString(username, config.user);
  const passOk = await verifyPassword(password, config.passwordHash);
  if (!(userOk && passOk)) {
    loginLimiter.recordFailure(ip);
    await sleep(FAILURE_DELAY_MS);
    return { username, error: "Wrong username or password." };
  }

  loginLimiter.reset(ip);
  const token = await signSession(config.user, config.secret);
  (await cookies()).set(SESSION_COOKIE, token, sessionCookieOptions(SESSION_TTL_SECONDS));
  redirect(next);
}

export async function logout(): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, "", sessionCookieOptions(0));
  redirect("/login");
}
