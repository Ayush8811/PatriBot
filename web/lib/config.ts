/** Public runtime config. NEXT_PUBLIC_* values are inlined at build time. */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/+$/, "");

/** NEXT_PUBLIC_API_MOCK=1 serves every API call from local fixtures (no backend needed). */
export const API_MOCK = process.env.NEXT_PUBLIC_API_MOCK === "1";

/** FR-26: ad slots exist but are off unless NEXT_PUBLIC_ADS_ENABLED=1. */
export const ADS_ENABLED = process.env.NEXT_PUBLIC_ADS_ENABLED === "1";

/** D13: free tier AI chat allowance (display only; the API is authoritative). */
export const FREE_DAILY_AI_QUERIES = 3;

/** IRCTC Advance Reservation Period (days). */
export const ARP_DAYS = 60;
