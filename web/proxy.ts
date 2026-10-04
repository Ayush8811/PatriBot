/**
 * Auth gate (Next.js 16 "Proxy", formerly Middleware). Runs before every route except build assets and the favicon:
 * - `/login` is public (its Server Function posts back to `/login`); a signed-in visitor is sent on to `next`.
 * - Everything else needs a valid session cookie: pages redirect to `/login?next=…`, `/api/*` gets 401 JSON
 *   (503 when sign-in is not configured: fail closed).
 * The API proxy route handler re-checks the session itself (defence in depth; see the Next.js data security guide).
 */
import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/auth/config";
import { loginRedirectPath, safeNextPath } from "@/lib/auth/next-param";
import { apiAuthError, authStateFromToken, isAllowed } from "@/lib/auth/session";

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const state = await authStateFromToken(request.cookies.get(SESSION_COOKIE)?.value);

  if (pathname === "/login") {
    if (state.status === "ok" && request.method === "GET") {
      const next = safeNextPath(request.nextUrl.searchParams.get("next"));
      return NextResponse.redirect(new URL(next, request.url));
    }
    return NextResponse.next();
  }

  if (isAllowed(state)) return NextResponse.next();

  if (pathname === "/api" || pathname.startsWith("/api/")) return apiAuthError(state);

  const target = new URL(loginRedirectPath(pathname, search), request.url);
  return NextResponse.redirect(target, request.method === "GET" || request.method === "HEAD" ? 307 : 303);
}

export const config = {
  // Everything except Next.js build assets, image optimisation and the favicon. (There is no public/ folder.)
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico$).*)"],
};
