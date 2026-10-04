/**
 * Per-IP login attempt limiter (in memory). Best effort: on serverless (Vercel) each warm instance has its own
 * memory and instances come and go, so this slows down a brute-force run but is not a hard global limit. The real
 * protection is a long random password + scrypt + the fixed failure delay.
 */
export interface LimiterOptions {
  maxFailures: number;
  windowMs: number;
  lockoutMs: number;
  maxKeys: number;
}

interface Entry {
  failures: number;
  firstAt: number;
  lockedUntil: number;
}

export class AttemptLimiter {
  private entries = new Map<string, Entry>();
  constructor(private readonly opts: LimiterOptions = { maxFailures: 5, windowMs: 15 * 60_000, lockoutMs: 15 * 60_000, maxKeys: 5000 }) {}

  /** Milliseconds until `key` may try again (0 = allowed now). */
  retryAfterMs(key: string, now = Date.now()): number {
    const e = this.entries.get(key);
    if (!e) return 0;
    if (e.lockedUntil > now) return e.lockedUntil - now;
    if (now - e.firstAt > this.opts.windowMs) this.entries.delete(key);
    return 0;
  }

  recordFailure(key: string, now = Date.now()): void {
    let e = this.entries.get(key);
    if (!e || now - e.firstAt > this.opts.windowMs) {
      e = { failures: 0, firstAt: now, lockedUntil: 0 };
    }
    e.failures += 1;
    if (e.failures >= this.opts.maxFailures) e.lockedUntil = now + this.opts.lockoutMs;
    this.entries.delete(key);
    this.entries.set(key, e);
    // Bound memory: drop the oldest keys (Map iterates in insertion order).
    while (this.entries.size > this.opts.maxKeys) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }

  reset(key: string): void {
    this.entries.delete(key);
  }
}

/** Process-wide limiter for the login form. */
export const loginLimiter = new AttemptLimiter();

/** Client IP from proxy headers. On Vercel `x-forwarded-for` is set by the platform (first entry = client). */
export function clientIp(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip")?.trim() || "unknown";
}
