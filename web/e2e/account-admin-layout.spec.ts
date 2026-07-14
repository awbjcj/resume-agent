import { expect, test, type Page } from "@playwright/test";

async function mockShell(page: Page) {
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs?*", (route) =>
    route.fulfill({
      json: {
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
      },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: { username: "owner", role: "admin", authRequired: false },
    }),
  );
}

test("account presents unlimited admin usage without narrow-screen overflow", async ({ page }) => {
  await mockShell(page);
  await page.route("**/api/account/usage", (route) =>
    route.fulfill({
      json: { weightedTotal: 12_400, ownKeyWeightedTotal: 820, budget: 0 },
    }),
  );
  await page.route("**/api/account/tokens", (route) =>
    route.fulfill({ json: { tokens: [] } }),
  );
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto("/account");

  await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
  await expect(page.getByText("No usage ceiling")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Personal access tokens" })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
});

test("admin makes the unlimited policy and member controls explicit", async ({ page }) => {
  await mockShell(page);
  await page.route("**/api/admin/system/defaults", (route) =>
    route.fulfill({
      json: {
        weeklyTokenBudget: 10_000_000,
        maxActiveJobs: 2_000,
        maxConcurrentRuns: 2,
      },
    }),
  );
  await page.route("**/api/admin/users", (route) =>
    route.fulfill({
      json: {
        users: [
          {
            id: "owner0000000",
            username: "owner",
            role: "admin",
            createdAt: "2026-07-01T00:00:00Z",
            disabledAt: null,
            weeklyTokenBudget: 1,
            maxActiveJobs: 1,
            maxConcurrentRuns: 1,
            weeklyUsage: 12_400,
            activeJobs: 14,
          },
        ],
      },
    }),
  );

  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await expect(page.getByText("Administrator access is unlimited")).toBeVisible();
  await expect(page.getByText("Member defaults")).toBeVisible();
  await expect(page.getByText("Tokens, jobs, and concurrency")).toBeVisible();
});
