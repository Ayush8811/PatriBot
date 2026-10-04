import { scryptSync } from "node:crypto";
import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

import { E2E_API_KEY, E2E_PASSWORD, E2E_SESSION_SECRET, E2E_USER } from "./e2e/credentials";

/** scrypt hash of the e2e password, same format as `npm run hash-password` (small N + fixed salt: test only). */
function e2ePasswordHash(): string {
  const N = 16384;
  const salt = Buffer.from("patribot-e2e-salt");
  const key = scryptSync(E2E_PASSWORD.normalize("NFKC"), salt, 32, { N, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
  return ["scrypt", N, 8, 1, salt.toString("base64"), key.toString("base64")].join("$");
}

/**
 * E2E smoke against a production build in mock mode (`next build && next start`, NEXT_PUBLIC_API_MOCK=1), with
 * auth ENABLED using throwaway e2e credentials (e2e/credentials.ts).
 * Locally we reuse a preinstalled Chromium when present (PLAYWRIGHT_CHROMIUM_EXECUTABLE or /opt/pw-browsers/chromium);
 * on CI `npx playwright install --with-deps chromium` provides the browser.
 */
const PORT = Number(process.env.E2E_PORT ?? 3100);
const preinstalled = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? "/opt/pw-browsers/chromium";
const executablePath = !process.env.CI && existsSync(preinstalled) ? preinstalled : undefined;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: {
    command: `npm run build && npx next start -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    env: {
      NEXT_PUBLIC_API_MOCK: "1",
      NEXT_TELEMETRY_DISABLED: "1",
      PATRIBOT_AUTH_USER: E2E_USER,
      PATRIBOT_AUTH_PASSWORD_HASH: e2ePasswordHash(),
      PATRIBOT_SESSION_SECRET: E2E_SESSION_SECRET,
      // Not used in mock mode; set so the build-output secret scan has a real value to look for.
      PATRIBOT_API_URL: "http://127.0.0.1:9",
      PATRIBOT_API_KEY: E2E_API_KEY,
      PATRIBOT_AUTH_DISABLED: "",
    },
    reuseExistingServer: !process.env.CI,
    timeout: 300_000,
  },
});
