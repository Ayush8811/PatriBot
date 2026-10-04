/**
 * Password hashing for the single owner account (server only: uses node:crypto).
 *
 * Format (self-describing, one line, safe to paste into an env var):
 *   scrypt$<N>$<r>$<p>$<saltB64>$<hashB64>
 * `scripts/hash-password.mjs` (npm run hash-password) produces the same format; a unit test keeps them in sync.
 */
import { createHash, randomBytes, scrypt, timingSafeEqual, type ScryptOptions } from "node:crypto";

export const SCRYPT_DEFAULTS = { N: 32768, r: 8, p: 1, keyLen: 32, saltLen: 16 } as const;

/** Upper bounds so a malformed hash can't make verification allocate gigabytes or spin for minutes. */
const MAX_N = 2 ** 20;
const MAX_R = 32;
const MAX_P = 16;

export interface ParsedHash {
  N: number;
  r: number;
  p: number;
  salt: Buffer;
  hash: Buffer;
}

function scryptAsync(password: string, salt: Buffer, keyLen: number, opts: ScryptOptions): Promise<Buffer> {
  return new Promise((resolve, reject) =>
    scrypt(password.normalize("NFKC"), salt, keyLen, opts, (err, key) => (err ? reject(err) : resolve(key))),
  );
}

function scryptOptions(N: number, r: number, p: number): ScryptOptions {
  // Node's default maxmem (32 MiB) is exactly 128*N*r for N=2^15, r=8, which scrypt rejects; give it headroom.
  return { N, r, p, maxmem: 256 * N * r + 1024 * 1024 };
}

const B64 = /^[A-Za-z0-9+/]+={0,2}$/;

export function parseHash(encoded: string): ParsedHash | null {
  if (typeof encoded !== "string") return null;
  const parts = encoded.trim().split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") return null;
  const [, n, r, p, salt, hash] = parts;
  if (![n, r, p].every((x) => /^\d{1,8}$/.test(x))) return null;
  const N = Number(n);
  const R = Number(r);
  const P = Number(p);
  // N must be a power of two > 1
  if (N < 2 || N > MAX_N || (N & (N - 1)) !== 0) return null;
  if (R < 1 || R > MAX_R || P < 1 || P > MAX_P) return null;
  if (!B64.test(salt) || !B64.test(hash)) return null;
  const saltBuf = Buffer.from(salt, "base64");
  const hashBuf = Buffer.from(hash, "base64");
  if (saltBuf.length < 8 || hashBuf.length < 16 || hashBuf.length > 128) return null;
  return { N, r: R, p: P, salt: saltBuf, hash: hashBuf };
}

export async function hashPassword(
  password: string,
  {
    N = SCRYPT_DEFAULTS.N as number,
    r = SCRYPT_DEFAULTS.r as number,
    p = SCRYPT_DEFAULTS.p as number,
    salt = randomBytes(SCRYPT_DEFAULTS.saltLen),
  } = {},
): Promise<string> {
  const key = await scryptAsync(password, salt, SCRYPT_DEFAULTS.keyLen, scryptOptions(N, r, p));
  return ["scrypt", N, r, p, salt.toString("base64"), key.toString("base64")].join("$");
}

/** Constant-time check of `password` against an encoded hash. Malformed hashes never verify. */
export async function verifyPassword(password: string, encoded: string): Promise<boolean> {
  const parsed = parseHash(encoded);
  if (!parsed || typeof password !== "string" || password.length === 0 || password.length > 1024) return false;
  try {
    const key = await scryptAsync(password, parsed.salt, parsed.hash.length, scryptOptions(parsed.N, parsed.r, parsed.p));
    return key.length === parsed.hash.length && timingSafeEqual(key, parsed.hash);
  } catch {
    return false;
  }
}

/** Constant-time string equality (for the username). Hashes both sides so lengths don't leak either. */
export function safeEqualString(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}
