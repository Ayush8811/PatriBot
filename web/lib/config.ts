/** Public runtime config. NEXT_PUBLIC_* values are inlined at build time: never put secrets in them. */

/**
 * Where the browser sends API calls. Default: the same-origin, session-checked proxy (`app/api/proxy`), which adds
 * the backend URL and key on the server. NEXT_PUBLIC_API_BASE_URL is an optional override for local development
 * against a local API without a key (e.g. http://localhost:8000/api/v1); leave it unset in deployments.
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api/proxy").replace(/\/+$/, "");

/** NEXT_PUBLIC_API_MOCK=1 serves every API call from local fixtures (no backend needed). */
export const API_MOCK = process.env.NEXT_PUBLIC_API_MOCK === "1";

/** FR-26: ad slots exist but are off unless NEXT_PUBLIC_ADS_ENABLED=1. */
export const ADS_ENABLED = process.env.NEXT_PUBLIC_ADS_ENABLED === "1";

/** D13: free tier AI chat allowance (display only; the API is authoritative). */
export const FREE_DAILY_AI_QUERIES = 3;

/** IRCTC Advance Reservation Period (days). */
export const ARP_DAYS = 60;
