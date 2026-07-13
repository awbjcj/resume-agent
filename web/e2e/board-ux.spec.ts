import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

test.beforeEach(async ({ page }) => {
  await mockEmptyRuns(page);
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) =>
    route.fulfill({
      json: {
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: {
          documentCount: 1,
          hasResume: true,
          factsBuiltAt: "2026-07-13T00:00:00Z",
          githubUsername: null,
        },
        search: { configured: true },
        sources: { enabledCount: 1 },
        complete: true,
      },
    }),
  );
  await page.route("**/api/shortlist*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            jobId: 7,
            company: "Acme",
            title: "Staff Engineer",
            location: "Remote",
            fitScore: 88,
            url: "https://jobs.example.test/7",
            skills: [],
          },
        ],
        pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        facets: {},
        total: 1,
      },
    }),
  );
});

test("switches board view, exposes quick actions, and opens import", async ({ page }) => {
  let archived: boolean | undefined;
  await page.route("**/api/jobs/7", async (route) => {
    if (route.request().method() === "PATCH") {
      archived = (route.request().postDataJSON() as { archived?: boolean }).archived;
      await route.fulfill({ json: {} });
      return;
    }
    await route.fallback();
  });

  await page.goto("/shortlist");
  await page.getByRole("button", { name: "List view" }).click();

  await expect(page).toHaveURL(/view=list/);
  await expect(page.getByRole("link", { name: "Open posting" })).toHaveAttribute(
    "href",
    "https://jobs.example.test/7",
  );
  await page.getByRole("button", { name: "Archive job" }).click();
  await expect.poll(() => archived).toBe(true);

  await page.getByRole("button", { name: /import file/i }).click();
  await expect(page.getByRole("heading", { name: "Import jobs" })).toBeVisible();
  await expect(page.getByLabel("Import file")).toHaveAttribute(
    "accept",
    ".csv,.json,.txt",
  );
});
