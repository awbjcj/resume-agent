import type { Page } from "@playwright/test";

export async function mockEmptyRuns(page: Page) {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: { username: null, role: null, authRequired: false },
    }));
  await page.route("**/api/runs?*", (route) =>
    route.fulfill({
      json: {
        data: [],
        pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
      },
    }));
  await page.route("**/api/interview/sessions*", (route) =>
    route.fulfill({ json: [] }),
  );
}
