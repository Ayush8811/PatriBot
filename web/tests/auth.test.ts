// @vitest-environment node
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { readAuthConfig } from "@/lib/auth/config";
import { loginRedirectPath, safeNextPath } from "@/lib/auth/next-param";
import { hashPassword, parseHash, safeEqualString, verifyPassword } from "@/lib/auth/password";
import { AttemptLimiter, clientIp } from "@/lib/auth/rate-limit";
import { SESSION_TTL_SECONDS, signSession, verifySession } from "@/lib/auth/token";

const SECRET = "test-session-secret-that-is-long-enough-0123456789";
// Small N keeps the tests fast; the format and code path are the same.
const FAST = { N: 1024, r: 8, p: 1 };

describe("password hash", () => {
  it("verifies the right password and rejects a wrong one", async () => {
    const h = await hashPassword("correct horse battery staple", FAST);
    expect(h).toMatch(/^scrypt\$1024\$8\$1\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/);
    expect(await verifyPassword("correct horse battery staple", h)).toBe(true);
    expect(await verifyPassword("correct horse battery stapl", h)).toBe(false);
    expect(await verifyPassword("", h)).toBe(false);
  });

  it("salts every hash", async () => {
    const a = await hashPassword("same", FAST);
    const b = await hashPassword("same", FAST);
    expect(a).not.toEqual(b);
  });

  it.each([
    ["empty", ""],
    ["wrong scheme", "bcrypt$1024$8$1$c2FsdHNhbHQ=$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["too few parts", "scrypt$1024$8$1$c2FsdHNhbHQ="],
    ["N not a power of two", "scrypt$1000$8$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["N too large", "scrypt$4194304$8$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["r zero", "scrypt$1024$0$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["non-numeric", "scrypt$abc$8$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["bad base64", "scrypt$1024$8$1$!!!$aGFzaGhhc2hoYXNoaGFzaA=="],
    ["short hash", "scrypt$1024$8$1$c2FsdHNhbHRzYWx0$aGFzaA=="],
    ["dotenv-expanded", "scrypt+c/==="],
  ])("rejects a malformed hash (%s)", async (_name, encoded) => {
    expect(parseHash(encoded)).toBeNull();
    expect(await verifyPassword("anything", encoded)).toBe(false);
  });

  it("npm run hash-password output verifies with the server code", async () => {
    const script = fileURLToPath(new URL("../scripts/hash-password.mjs", import.meta.url));
    const res = spawnSync(process.execPath, [script], { input: "a long test passphrase\n", encoding: "utf8" });
    expect(res.status).toBe(0);
    const line = res.stdout.trim();
    expect(line.split("\n")).toHaveLength(1);
    expect(parseHash(line)).not.toBeNull();
    expect(await verifyPassword("a long test passphrase", line)).toBe(true);
    expect(await verifyPassword("a long test passphrasE", line)).toBe(false);
  });

  it("compares usernames in constant time without leaking length", () => {
    expect(safeEqualString("owner", "owner")).toBe(true);
    expect(safeEqualString("owner", "owner2")).toBe(false);
    expect(safeEqualString("", "owner")).toBe(false);
  });
});

describe("session token", () => {
  const now = Date.UTC(2026, 9, 4, 12, 0, 0);

  it("signs and verifies", async () => {
    const t = await signSession("owner", SECRET, { now });
    const p = await verifySession(t, SECRET, { now: now + 1000, expectedUser: "owner" });
    expect(p).toMatchObject({ sub: "owner", v: 1 });
    expect(p!.exp - p!.iat).toBe(SESSION_TTL_SECONDS);
  });

  it("expires after 30 days", async () => {
    const t = await signSession("owner", SECRET, { now });
    expect(await verifySession(t, SECRET, { now: now + (SESSION_TTL_SECONDS - 60) * 1000 })).not.toBeNull();
    expect(await verifySession(t, SECRET, { now: now + SESSION_TTL_SECONDS * 1000 })).toBeNull();
  });

  it("rejects a tampered payload or signature", async () => {
    const t = await signSession("owner", SECRET, { now });
    const [body, sig] = t.split(".");
    const forged = Buffer.from(JSON.stringify({ sub: "owner", iat: now / 1000, exp: now / 1000 + 10 ** 9, v: 1 })).toString(
      "base64url",
    );
    expect(await verifySession(`${forged}.${sig}`, SECRET, { now })).toBeNull();
    const flipped = sig!.slice(0, -2) + (sig!.endsWith("AA") ? "BB" : "AA");
    expect(await verifySession(`${body}.${flipped}`, SECRET, { now })).toBeNull();
    expect(await verifySession(`${body}`, SECRET, { now })).toBeNull();
    expect(await verifySession(`${body}.${sig}.x`, SECRET, { now })).toBeNull();
    expect(await verifySession("", SECRET, { now })).toBeNull();
    expect(await verifySession(undefined, SECRET, { now })).toBeNull();
  });

  it("rejects another secret, another user and a too-short secret", async () => {
    const t = await signSession("owner", SECRET, { now });
    expect(await verifySession(t, `${SECRET}x`, { now })).toBeNull();
    expect(await verifySession(t, SECRET, { now, expectedUser: "someone" })).toBeNull();
    expect(await verifySession(t, "short", { now })).toBeNull();
    await expect(signSession("owner", "short")).rejects.toThrow(/at least 32/);
  });

  it("rejects tokens with a lifetime longer than ours", async () => {
    const t = await signSession("owner", SECRET, { now, ttlSeconds: SESSION_TTL_SECONDS * 10 });
    expect(await verifySession(t, SECRET, { now })).toBeNull();
  });
});

describe("next param", () => {
  it.each([
    ["/plan?origin=KOLKATA&destination=DELHI", "/plan?origin=KOLKATA&destination=DELHI"],
    ["/trains/12301", "/trains/12301"],
    ["/", "/"],
    [null, "/"],
    ["", "/"],
    ["https://evil.example/", "/"],
    ["//evil.example/", "/"],
    ["/\\evil.example", "/"],
    ["\\\\evil.example", "/"],
    ["/\tevil", "/"],
    ["/%0d%0aSet-Cookie:x", "/%0d%0aSet-Cookie:x"],
    ["javascript:alert(1)", "/"],
    ["/login", "/"],
    ["/login?next=/x", "/"],
    ["/api/proxy/plan", "/"],
    ["/../../etc/passwd", "/etc/passwd"],
  ])("safeNextPath(%j) = %j", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it("builds the login redirect", () => {
    expect(loginRedirectPath("/")).toBe("/login");
    expect(loginRedirectPath("/plan", "?a=1&b=2")).toBe("/login?next=%2Fplan%3Fa%3D1%26b%3D2");
  });
});

describe("auth config", () => {
  const good = {
    PATRIBOT_AUTH_USER: "owner",
    PATRIBOT_AUTH_PASSWORD_HASH: "scrypt$1024$8$1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA==",
    PATRIBOT_SESSION_SECRET: SECRET,
    NODE_ENV: "production",
  };

  it("is enabled with all vars", () => {
    expect(readAuthConfig(good).mode).toBe("enabled");
  });

  it("fails closed when anything is missing or weak", () => {
    expect(readAuthConfig({ NODE_ENV: "production" }).mode).toBe("misconfigured");
    expect(readAuthConfig({ ...good, PATRIBOT_SESSION_SECRET: "short" }).mode).toBe("misconfigured");
    expect(readAuthConfig({ ...good, PATRIBOT_AUTH_PASSWORD_HASH: "hunter2" }).mode).toBe("misconfigured");
    expect(readAuthConfig({ ...good, PATRIBOT_AUTH_USER: " " }).mode).toBe("misconfigured");
  });

  it("only honours PATRIBOT_AUTH_DISABLED in mock mode or next dev", () => {
    expect(readAuthConfig({ PATRIBOT_AUTH_DISABLED: "1", NODE_ENV: "production" }).mode).toBe("misconfigured");
    expect(readAuthConfig({ ...good, PATRIBOT_AUTH_DISABLED: "1" }).mode).toBe("enabled");
    expect(readAuthConfig({ PATRIBOT_AUTH_DISABLED: "1", NEXT_PUBLIC_API_MOCK: "1", NODE_ENV: "production" }).mode).toBe("disabled");
    expect(readAuthConfig({ PATRIBOT_AUTH_DISABLED: "1", NODE_ENV: "development" }).mode).toBe("disabled");
    expect(readAuthConfig({ NEXT_PUBLIC_API_MOCK: "1", NODE_ENV: "production" }).mode).toBe("misconfigured");
  });
});

describe("login attempt limiter", () => {
  it("locks an IP out after repeated failures and resets on success", () => {
    const l = new AttemptLimiter({ maxFailures: 3, windowMs: 60_000, lockoutMs: 120_000, maxKeys: 10 });
    const t0 = 1_000_000;
    l.recordFailure("1.2.3.4", t0);
    l.recordFailure("1.2.3.4", t0 + 1);
    expect(l.retryAfterMs("1.2.3.4", t0 + 2)).toBe(0);
    l.recordFailure("1.2.3.4", t0 + 2);
    expect(l.retryAfterMs("1.2.3.4", t0 + 3)).toBeGreaterThan(100_000);
    expect(l.retryAfterMs("5.6.7.8", t0 + 3)).toBe(0);
    expect(l.retryAfterMs("1.2.3.4", t0 + 130_000)).toBe(0);
    l.recordFailure("9.9.9.9", t0);
    l.reset("9.9.9.9");
    expect(l.retryAfterMs("9.9.9.9", t0)).toBe(0);
  });

  it("bounds memory", () => {
    const l = new AttemptLimiter({ maxFailures: 1, windowMs: 60_000, lockoutMs: 60_000, maxKeys: 3 });
    for (let i = 0; i < 10; i++) l.recordFailure(`ip${i}`, 0);
    expect(l.retryAfterMs("ip0", 1)).toBe(0);
    expect(l.retryAfterMs("ip9", 1)).toBeGreaterThan(0);
  });

  it("takes the client IP from the first x-forwarded-for entry", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "203.0.113.9, 10.0.0.1" }))).toBe("203.0.113.9");
    expect(clientIp(new Headers({ "x-real-ip": "203.0.113.7" }))).toBe("203.0.113.7");
    expect(clientIp(new Headers())).toBe("unknown");
  });
});
