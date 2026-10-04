import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

/**
 * E2E smoke against a production build in mock mode (`next build && next start`, NEXT_PUBLIC_API_MOCK=1).
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
    env: { NEXT_PUBLIC_API_MOCK: "1", NEXT_TELEMETRY_DISABLED: "1" },
    reuseExistingServer: !process.env.CI,
    timeout: 300_000,
  },
});
