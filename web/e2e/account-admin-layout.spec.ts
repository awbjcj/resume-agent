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

test("cost quotas keeps one sidebar destination active and contains narrow layouts", async ({ page }) => {
  await mockShell(page);
  const paged = (data: unknown[]) => ({
    data,
    pagination: { page: 1, pageSize: 100, totalItems: data.length, totalPages: 1 },
  });
  await page.route("**/api/admin/quota-summary", (route) => route.fulfill({ json: {
    monthlySpendMicros: 125_000_000,
    monthlyCapMicros: 500_000_000,
    remainingMicros: 375_000_000,
    unpricedCallCount: 2,
    nextResetAt: "2026-08-01T00:00:00Z",
  } }));
  await page.route("**/api/admin/quota-tiers?*", (route) => route.fulfill({ json: paged([]) }));
  await page.route("**/api/admin/quota-accounts?*", (route) => route.fulfill({ json: paged([]) }));
  await page.route("**/api/admin/llm-rates?*", (route) => route.fulfill({ json: paged([]) }));
  await page.route("**/api/admin/quota-operations?*", (route) => route.fulfill({ json: paged([]) }));

  await page.goto("/admin/quotas");

  await expect(page.getByRole("heading", { name: "Cost quotas" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Cost quotas" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Admin", exact: true })).not.toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "View my usage" })).toHaveAttribute("href", "/account");

  const memberSearch = page.getByRole("textbox", { name: "Search members" });
  const balanceFilter = page.getByRole("combobox", { name: "Balance filter" });
  await expect(memberSearch).toHaveCSS("height", "36px");
  await expect(balanceFilter).toHaveCSS("height", "36px");

  await page.getByRole("tab", { name: "Tiers" }).click();
  await page.getByRole("button", { name: "New tier" }).click();
  const tierName = page.getByLabel("Tier name");
  const tierReason = page.getByLabel("Reason for this new tier");
  const tierCadence = page.getByRole("combobox", { name: "New tier cycle period" });
  const tierCount = page.getByRole("combobox", { name: "New tier cycle count" });
  for (const control of [tierName, tierReason, tierCadence, tierCount]) {
    await expect(control).toHaveCSS("height", "36px");
  }
  const tierNameBox = await tierName.boundingBox();
  const createTierBox = await page.getByRole("button", { name: "Create tier" }).boundingBox();
  expect(createTierBox?.x).toBeGreaterThan(tierNameBox?.x ?? 0);

  await page.getByRole("tab", { name: "Rate cards" }).click();
  const rateProvider = page.getByRole("combobox", { name: "Rate provider" });
  const rateModel = page.getByRole("combobox", { name: "Rate model" });
  const customModel = page.getByLabel("Model identifier");
  const rateReason = page.locator("#rate-reason");
  for (const control of [rateProvider, rateModel, customModel, rateReason]) {
    await expect(control).toHaveCSS("height", "36px");
  }
  const rateReasonBox = await rateReason.boundingBox();
  const createRateBox = await page.getByRole("button", { name: "Create immutable version" }).boundingBox();
  expect(createRateBox?.x).toBeGreaterThan(rateReasonBox?.x ?? 0);

  await page.getByRole("switch", { name: "Optional cache and tool rates" }).click();
  const optionalRateFields = [
    page.getByLabel("Cache read (USD / 1M)"),
    page.getByLabel("Cache write (USD / 1M)"),
    page.getByLabel("Tool fee (USD / unit)"),
  ];
  const optionalRateBoxes = await Promise.all(optionalRateFields.map((field) => field.boundingBox()));
  const expandedReasonBox = await rateReason.boundingBox();
  for (const box of optionalRateBoxes) {
    expect(Math.abs((box?.y ?? 0) - (expandedReasonBox?.y ?? 0))).toBeLessThanOrEqual(1);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  const rateOptionsRow = page.getByTestId("rate-options-row");
  await expect(rateOptionsRow).toHaveCSS("flex-wrap", "nowrap");
  const portableRateBoxes = await Promise.all(
    [...optionalRateFields, rateReason].map((field) => field.boundingBox()),
  );
  const portableRateY = portableRateBoxes[0]?.y ?? 0;
  for (const box of portableRateBoxes.slice(1)) {
    expect(Math.abs((box?.y ?? 0) - portableRateY)).toBeLessThanOrEqual(1);
  }
  const rateOptionsRail = rateOptionsRow.locator("..");
  const rateOptionsWidths = await rateOptionsRail.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(rateOptionsWidths.scrollWidth).toBeGreaterThan(rateOptionsWidths.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole("tab", { name: "Tiers" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
