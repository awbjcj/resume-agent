import { test, expect } from "@playwright/test";

// Hermetic smoke: intercept the API so no backend is required.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/shortlist*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            jobId: 1,
            company: "Acme",
            title: "Staff Engineer",
            location: "Remote",
            fitScore: 81,
            skills: [],
          },
        ],
        pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
      },
    }),
  );
});

test("loads shortlist and opens a job drawer", async ({ page }) => {
  await page.route("**/api/jobs/1", (route) =>
    route.fulfill({
      json: {
        id: 1,
        source: "greenhouse",
        url: null,
        company: "Acme",
        title: "Staff Engineer",
        location: "Remote",
        jdText: "Build.",
        status: "shortlisted",
        fitScore: 81,
        fitRationale: null,
        criteriaJson: null,
        postedAt: null,
        archivedAt: null,
        createdAt: "2026-06-01T00:00:00Z",
        hasProgress: false,
        application: null,
        resumeVersions: [],
        skills: [],
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Staff Engineer")).toBeVisible();
  await page.getByText("Staff Engineer").click();
  await expect(page.getByRole("heading", { name: /staff engineer/i })).toBeVisible();
});
