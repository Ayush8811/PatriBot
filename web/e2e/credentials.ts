/**
 * Throwaway credentials for the e2e run only (the server is started with a hash of this password). These values are
 * not used anywhere else; the e2e run greps the build output to prove the secrets don't reach client bundles.
 */
export const E2E_USER = "e2e-owner";
export const E2E_PASSWORD = "e2e correct horse battery staple";
export const E2E_SESSION_SECRET = "e2e-session-secret-NOT-FOR-PRODUCTION-5f3c9a1b7d2e";
export const E2E_API_KEY = "e2e-api-key-NOT-FOR-PRODUCTION-8b41d07c";
