/**
 * Stateless session token: `<payloadB64url>.<hmacB64url>`, HMAC-SHA256 over the payload segment with
 * PATRIBOT_SESSION_SECRET. Web Crypto only, so it runs in Proxy, Route Handlers and Server Functions alike.
 * No database: logging out deletes the cookie; rotating the secret invalidates every session.
 */
export const SESSION_TTL_SECONDS = 30 * 24 * 60 * 60;
export const MIN_SECRET_LENGTH = 32;

export interface SessionPayload {
  /** username */
  sub: string;
  /** issued at, unix seconds */
  iat: number;
  /** expires at, unix seconds */
  exp: number;
  v: 1;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64urlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): Uint8Array<ArrayBuffer> | null {
  if (!/^[A-Za-z0-9_-]*$/.test(s)) return null;
  try {
    const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

const keyCache = new Map<string, Promise<CryptoKey>>();

function hmacKey(secret: string): Promise<CryptoKey> {
  let key = keyCache.get(secret);
  if (!key) {
    key = crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
    if (keyCache.size > 4) keyCache.clear();
    keyCache.set(secret, key);
  }
  return key;
}

function assertSecret(secret: string) {
  if (typeof secret !== "string" || secret.length < MIN_SECRET_LENGTH) {
    throw new Error(`session secret must be at least ${MIN_SECRET_LENGTH} characters`);
  }
}

export async function signSession(
  username: string,
  secret: string,
  { now = Date.now(), ttlSeconds = SESSION_TTL_SECONDS } = {},
): Promise<string> {
  assertSecret(secret);
  const iat = Math.floor(now / 1000);
  const payload: SessionPayload = { sub: username, iat, exp: iat + ttlSeconds, v: 1 };
  const body = b64urlEncode(enc.encode(JSON.stringify(payload)));
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(body)));
  return `${body}.${b64urlEncode(sig)}`;
}

/**
 * Returns the payload when the signature is valid (constant-time, via `crypto.subtle.verify`), the token has not
 * expired and, when given, the subject matches `expectedUser`. Otherwise null. Never throws.
 */
export async function verifySession(
  token: string | undefined | null,
  secret: string,
  { now = Date.now(), expectedUser }: { now?: number; expectedUser?: string } = {},
): Promise<SessionPayload | null> {
  if (!token || typeof token !== "string" || token.length > 2048) return null;
  if (typeof secret !== "string" || secret.length < MIN_SECRET_LENGTH) return null;
  const dot = token.indexOf(".");
  if (dot <= 0 || dot !== token.lastIndexOf(".")) return null;
  const body = token.slice(0, dot);
  const sig = b64urlDecode(token.slice(dot + 1));
  if (!sig || sig.length !== 32) return null;
  let ok = false;
  try {
    ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), sig, enc.encode(body));
  } catch {
    return null;
  }
  if (!ok) return null;
  const raw = b64urlDecode(body);
  if (!raw) return null;
  let payload: SessionPayload;
  try {
    payload = JSON.parse(dec.decode(raw)) as SessionPayload;
  } catch {
    return null;
  }
  if (
    !payload ||
    payload.v !== 1 ||
    typeof payload.sub !== "string" ||
    typeof payload.exp !== "number" ||
    typeof payload.iat !== "number"
  ) {
    return null;
  }
  const nowSec = Math.floor(now / 1000);
  if (payload.exp <= nowSec) return null;
  // Tokens from the future (clock skew > 5 min) or with a lifetime longer than ours are not ours.
  if (payload.iat > nowSec + 300 || payload.exp - payload.iat > SESSION_TTL_SECONDS) return null;
  if (expectedUser !== undefined && payload.sub !== expectedUser) return null;
  return payload;
}
