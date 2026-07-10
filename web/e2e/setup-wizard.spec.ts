import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

const INCOMPLETE_STATUS = {
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false },
  sources: { enabledCount: 0 },
  complete: false,
};

// Hermetic smoke: intercept the API so no backend is required, matching the
// pattern in e2e/smoke.spec.ts and e2e/sources.spec.ts.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: INCOMPLETE_STATUS }));
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await mockEmptyRuns(page);
  await page.route("**/api/dashboard/summary", (route) =>
    route.fulfill({
      json: {
        statusCounts: {},
        queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
        applied: 0,
      },
    }));
  await page.route("**/api/secrets", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/profile/documents", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/config/profile", (route) =>
    route.fulfill({ json: { githubUsername: null } }));
  await page.route("**/api/config/search", (route) =>
    route.fulfill({
      json: {
        keywords: [], titles: [], locations: [], remotePolicy: null,
        minSalary: null, yoeMin: null, yoeMax: null, sponsorshipRequired: false,
        roleAnchors: [], excludeTerms: [], targetRole: null,
        distance: null, maxDaysOld: null, experienceLevels: [], employmentTypes: [],
      },
    }));
});

test("first run gates to the wizard; exit reaches the app; settings nav works", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup/);
  await expect(page.getByText("First-run setup")).toBeVisible();

  await page.getByRole("button", { name: "Exit setup" }).click();
  await expect(page).not.toHaveURL(/\/setup/);

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings\/profile/);
  await page.getByRole("link", { name: "Search" }).click();
  await expect(page.getByLabel("Keywords")).toBeVisible();
});
