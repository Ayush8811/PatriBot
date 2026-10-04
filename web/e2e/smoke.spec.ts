import { expect, test, type Page } from "@playwright/test";

import { E2E_PASSWORD, E2E_USER } from "./credentials";

const SHOTS = "e2e/screenshots";

async function login(page: Page, path = "/") {
  await page.goto(path);
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(E2E_USER);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test("auth: redirect to login → wrong password → login → search → logout", async ({ page }) => {
  await page.goto("/trains/12301");
  await expect(page).toHaveURL(/\/login\?next=%2Ftrains%2F12301$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in to PatriBot");
  // No app navigation for signed-out visitors
  await expect(page.getByRole("link", { name: "Ask AI" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/desktop-login.png`, fullPage: false });

  // API calls without a session get 401 JSON, not data
  const api = await page.request.get("/api/proxy/health");
  expect(api.status()).toBe(401);
  expect(await api.json()).toEqual({ detail: "Not signed in." });

  await page.getByLabel("Username").fill(E2E_USER);
  await page.getByLabel("Password").fill("wrong password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#login-error")).toContainText("Wrong username or password.");
  await expect(page).toHaveURL(/\/login/);
  await page.screenshot({ path: `${SHOTS}/desktop-login-error.png`, fullPage: false });

  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // lands on the page it was trying to reach
  await expect(page).toHaveURL(/\/trains\/12301$/);
  await expect(page.getByTestId("signed-in-user")).toHaveText(E2E_USER);

  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "patribot_session");
  expect(session).toBeDefined();
  expect(session!.httpOnly).toBe(true);
  expect(session!.sameSite).toBe("Lax");
  expect(session!.secure).toBe(true); // next start = production

  await searchKolkataDelhi(page);

  // a signed-in visitor going to /login is sent on
  await page.goto("/login?next=%2Fchat");
  await expect(page).toHaveURL(/\/chat$/);

  await page.getByRole("button", { name: /log out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});

test("login rejects open redirects in next", async ({ page }) => {
  await page.goto("/login?next=https%3A%2F%2Fevil.example%2F");
  await page.getByLabel("Username").fill(E2E_USER);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/^http:\/\/(127\.0\.0\.1|localhost):\d+\/$/);
});

async function searchKolkataDelhi(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("actually");
  await page.getByRole("combobox", { name: "From" }).fill("Kolk");
  await page.getByRole("option", { name: /Kolkata \(all stations\)/ }).click();
  await page.getByRole("combobox", { name: "To" }).fill("Delh");
  await page.getByRole("option", { name: /Delhi \(all stations\)/ }).click();
  await page.getByRole("button", { name: /find trains/i }).click();
  await expect(page).toHaveURL(/\/plan\?/);
  await expect(page.getByTestId("itinerary-card").first()).toBeVisible();
}

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("search → results → why this → train page", async ({ page }) => {
    await searchKolkataDelhi(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Kolkata");
    const cards = page.getByTestId("itinerary-card");
    expect(await cards.count()).toBeGreaterThanOrEqual(3);
    await expect(page.locator('[data-testid="itinerary-card"][data-kind="split"]').first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/desktop-results.png`, fullPage: false });
    const splitCard = page.locator('[data-testid="itinerary-card"][data-kind="split"]').first();
    await splitCard.scrollIntoViewIfNeeded();
    await page.emulateMedia({ colorScheme: "dark" });
    await splitCard.screenshot({ path: `${SHOTS}/desktop-split-card-dark.png` });
    await page.emulateMedia({ colorScheme: "light" });
    await page.evaluate(() => window.scrollTo(0, 0));

    const first = cards.first();
    await first.getByRole("button", { name: /why this/i }).click();
    await expect(first.getByTestId("why-this")).toContainText("Score breakdown");

    // Sorting chips re-order without errors
    await page.getByRole("radio", { name: "Most reliable" }).click();
    await expect(cards.first()).toBeVisible();

    await first.getByRole("link", { name: /^\d{5} / }).first().click();
    await expect(page).toHaveURL(/\/trains\/\d{5}$/);
    await expect(page.getByText("Route and typical delay at each stop")).toBeVisible();
    await expect(page.getByRole("list", { name: "Route" }).getByRole("listitem").first()).toBeVisible();
    await expect(page.getByText("Monthly performance", { exact: true })).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/desktop-train.png`, fullPage: true });
  });

  test("Ask AI shows Coming soon and never calls /chat", async ({ page }) => {
    const chatCalls: string[] = [];
    page.on("request", (r) => {
      if (new URL(r.url()).pathname.endsWith("/chat") && r.method() === "POST") chatCalls.push(r.url());
    });
    await page.getByRole("link", { name: "Ask AI" }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByText("Coming soon", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ask PatriBot in plain language");
    await expect(page.getByText(/Overnight train Kolkata → Delhi, Nov 20–30/)).toBeVisible();
    await expect(page.getByLabel("Message PatriBot")).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/desktop-coming-soon.png`, fullPage: true });
    await page.getByRole("link", { name: "Search trains" }).click();
    await expect(page).toHaveURL(/\/$/);
    expect(chatCalls).toEqual([]);
  });

  test("mobile home and results @mobile", async ({ page }) => {
    await page.goto("/");
    await page.screenshot({ path: `${SHOTS}/mobile-home.png`, fullPage: false });
    await searchKolkataDelhi(page);
    expect(await page.getByTestId("itinerary-card").count()).toBeGreaterThanOrEqual(3);
    // no horizontal scroll on a phone
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/mobile-results.png`, fullPage: false });
  });
});
