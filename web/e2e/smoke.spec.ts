import { expect, test, type Page } from "@playwright/test";

const SHOTS = "e2e/screenshots";

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

test("chat streams a reply with itinerary cards", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByTestId("queries-left")).toContainText("3 free AI queries");
  await page.getByLabel("Message PatriBot").fill("Overnight train Kolkata to Delhi next weekend");
  await page.getByRole("button", { name: "Send" }).click();
  const reply = page.getByTestId("assistant-text").last();
  await expect(reply).toContainText("I found");
  // still streaming: the text keeps growing until "done"
  await expect(reply).toContainText("Cards below have the details.");
  await expect(page.getByTestId("itinerary-card").first()).toBeVisible();
  await expect(page.getByTestId("queries-left")).toContainText("2 AI queries left today");
  await page.screenshot({ path: `${SHOTS}/desktop-chat.png`, fullPage: false });
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
