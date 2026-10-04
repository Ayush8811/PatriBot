/**
 * Plan/quota placeholder used by the (currently unused) Phase 4 chat UI. Client-safe: no secrets here.
 *
 * Access control is single-owner username + password (owner decision): see lib/auth/{config,password,token,
 * session,actions}.ts, proxy.ts and docs/phase3/web-app.md "Auth & proxy". Multi-user accounts (FR-22, Auth.js +
 * Google, per-user AI quota FR-23 / D13) are a later phase.
 */
import { FREE_DAILY_AI_QUERIES } from "@/lib/config";

export type Plan = "free" | "paid";

export interface Session {
  user: { name: string; email: string; image?: string } | null;
  plan: Plan;
  /** AI chat allowance shown in the UI; the backend enforces it. */
  dailyAiQueries: number;
}

export function getSession(): Session {
  return { user: null, plan: "free", dailyAiQueries: FREE_DAILY_AI_QUERIES };
}
