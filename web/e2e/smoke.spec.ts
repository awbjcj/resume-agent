import { test, expect } from "@playwright/test";

// Hermetic smoke: intercept the API so no backend is required.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  // SetupGate (wraps the whole app shell) fetches this on every page load.
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
            industry: "Autonomous Driving",
            skills: [],
          },
        ],
        pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        facets: { industry: { "Autonomous Driving": 1 } },
        total: 1,
      },
    }),
  );
});

test("loads shortlist and opens a job drawer", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
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
        industry: "Autonomous Driving",
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
  await page.goto("/shortlist");
  await expect(page.getByText("Staff Engineer")).toBeVisible();
  await page.getByRole("button", { name: "Industry" }).click();
  await expect(
    page.getByRole("checkbox", { name: "Autonomous Driving" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByText("Staff Engineer").click();
  await expect(page.getByRole("heading", { name: /staff engineer/i })).toBeVisible();
  await expect(
    page.getByRole("dialog").getByText("Autonomous Driving"),
  ).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("min-fit numeric input applies the server filter", async ({ page }) => {
  await page.goto("/shortlist");
  const minFit = page.getByRole("spinbutton", { name: "Min fit" });

  await minFit.fill("65");
  const filteredRequest = page.waitForRequest(
    (request) => new URL(request.url()).searchParams.get("minFit") === "65",
  );
  await page.getByRole("button", { name: /apply filters/i }).click();

  await filteredRequest;
  await expect(minFit).toHaveValue("65");
});
