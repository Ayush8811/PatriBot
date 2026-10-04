/**
 * Validate the `?next=` redirect target after login: only same-origin relative paths are allowed. Anything else
 * (absolute URLs, protocol-relative `//evil.com`, backslash tricks, control characters, the login page itself) falls
 * back to "/". Prevents open redirects.
 */
export function safeNextPath(next: string | null | undefined, fallback = "/"): string {
  if (typeof next !== "string" || next.length === 0 || next.length > 2048) return fallback;
  // Must be a path: a single leading slash, no scheme, no authority.
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  // Browsers treat "\" like "/" and strip tabs/newlines, so reject them and any other control characters.
  if (/[\\\u0000-\u001f\u007f]/.test(next)) return fallback;
  let url: URL;
  try {
    url = new URL(next, "http://patribot.invalid");
  } catch {
    return fallback;
  }
  if (url.origin !== "http://patribot.invalid") return fallback;
  if (url.pathname === "/login" || url.pathname.startsWith("/login/")) return fallback;
  if (url.pathname.startsWith("/api/")) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Build `/login?next=<path+search>` for a request that needs a session. */
export function loginRedirectPath(pathname: string, search = ""): string {
  const target = safeNextPath(`${pathname}${search}`, "");
  return target && target !== "/" ? `/login?${new URLSearchParams({ next: target })}` : "/login";
}
