/** Same-origin proxy to the FastAPI backend (see lib/api/proxy-handler.ts). */
import { proxyToApi } from "@/lib/api/proxy-handler";

// Upstream timeout is 90 s (API cold start); give the function a little more than that.
export const maxDuration = 120;

export async function GET(request: Request, ctx: RouteContext<"/api/proxy/[...path]">) {
  const { path } = await ctx.params;
  return proxyToApi(request, path);
}

export async function POST(request: Request, ctx: RouteContext<"/api/proxy/[...path]">) {
  const { path } = await ctx.params;
  return proxyToApi(request, path);
}
