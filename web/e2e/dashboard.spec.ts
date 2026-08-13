import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

// Hermetic smoke: intercept the API so no backend is required, matching the
// pattern in e2e/smoke.spec.ts and e2e/setup-wizard.spec.ts.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await mockEmptyRuns(page);
  await page.route("**/api/setup/status", (route) =>
    route.fulfill({
      json: {
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-06-01T00:00:00Z", githubUsername: null },
        search: { configured: true },
        sources: { enabledCount: 1 },
        complete: true,
      },
    }));
  await page.route("**/api/dashboard/summary", (route) =>
    route.fulfill({
      json: {
        statusCounts: {
          raw: 3, extracted: 1, filtered: 2, rejected: 1,
          shortlisted: 4, approved: 1, tailored: 2, rendered: 1,
        },
        queues: { triage: 2, approve: 4, tailor: 1, apply: 1 },
        applied: 5,
      },
    }));
  await page.route("**/api/shortlist*", (route) =>
    route.fulfill({
      json: {
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
        facets: {},
        total: 0,
      },
    }));
  await page.route("**/api/triage*", (route) =>
    route.fulfill({
      json: {
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
        facets: {},
        total: 0,
      },
    }));
});

test("dashboard is home and queue cards deep-link", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /waiting on you/i }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Shortlist", exact: true }).click();
  await expect(page).toHaveURL(/\/shortlist/);

  await page.goBack();
  await page
    .getByRole("link", { name: /triage 2/i })
    .click();
  await expect(page).toHaveURL(/\/triage/);
});

test("mobile chrome keeps launch actions compact and horizontally contained", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const chrome = page.locator("header.app-chrome");
  await expect(chrome.getByText("Resume Agent", { exact: true })).toBeVisible();

  const chromeBox = await chrome.boundingBox();
  expect(chromeBox).not.toBeNull();
  expect(chromeBox!.height).toBeLessThanOrEqual(128);

  const rail = chrome.locator(".shell-action-rail");
  const railDimensions = await rail.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(railDimensions.scrollWidth).toBeGreaterThan(railDimensions.clientWidth);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
});
