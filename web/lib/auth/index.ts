/**
 * Auth stub (FR-22, architecture §10: Auth.js with Google sign-in).
 *
 * TODO(phase: accounts): replace with Auth.js (`next-auth`) configured with the Google provider:
 *   - `auth.ts` at the web root exporting `{ handlers, auth, signIn, signOut }`
 *   - `app/api/auth/[...nextauth]/route.ts` re-exporting `handlers`
 *   - env: AUTH_SECRET, AUTH_GOOGLE_ID, AUTH_GOOGLE_SECRET (never committed; see docs/phase3/web-app.md)
 *   - forward the session to the FastAPI backend so it can meter AI chat quota per user (FR-23, D13)
 * Until then everyone is an anonymous free-tier visitor; the API is the source of truth for quota.
 */
import { FREE_DAILY_AI_QUERIES } from "@/lib/config";

export type Plan = "free" | "paid";

export interface Session {
  user: { name: string; email: string; image?: string } | null;
  plan: Plan;
  /** AI chat allowance shown in the UI; the backend enforces it. */
  dailyAiQueries: number;
}

export const AUTH_ENABLED = false;

export function getSession(): Session {
  return { user: null, plan: "free", dailyAiQueries: FREE_DAILY_AI_QUERIES };
}
