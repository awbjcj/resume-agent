import { expect, test, type Page } from "@playwright/test";

const activeCareerLab = {
  sessionId: "career-1", title: "Offer strategy", goal: "Compare two offers", startedAt: "2026-08-02T12:00:00Z", endedAt: null, status: "active", archivedAt: null, turnCount: 1,
};

async function mockCareerLab(page: Page, active = false) {
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { username: null, role: null, authRequired: false } }));
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/transcribe/availability", (route) => route.fulfill({ json: { available: false } }));
  await page.route("**/api/runs?*", (route) => route.fulfill({ json: { data: [], pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 } } }));
  await page.route("**/api/interview/sessions", (route) => route.fulfill({ json: { sessions: [] } }));
  await page.route("**/api/interview/sessions?*", (route) => route.fulfill({ json: { sessions: [] } }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: { secrets: { anthropicKey: true, anyLlmKey: true }, profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-08-01T00:00:00Z", githubUsername: null }, search: { configured: true }, sources: { enabledCount: 1 }, complete: true } }));
  await page.route("**/api/career-lab/skills", (route) => route.fulfill({ json: { skills: [{ name: "salary-negotiation-prep", description: "Prepare negotiation points.", family: "career_lab", uses: ["career_lab"], isAvailable: true, unavailableReason: null }] } }));
  await page.route("**/api/career-lab/sessions?*", (route) => route.fulfill({ json: { sessions: active ? [activeCareerLab] : [], pagination: { page: 1, pageSize: 20, totalItems: active ? 1 : 0, totalPages: 1 } } }));
  if (active) {
    await page.route("**/api/career-lab/sessions/career-1", (route) => route.fulfill({ json: { ...activeCareerLab, turns: [] } }));
  }
  await page.route("**/api/pipeline?*", (route) => route.fulfill({ json: {
    data: [
      { jobId: 7, company: "Acme", title: "Staff Engineer", source: "linkedin", location: "New York", status: "tailored", fitScore: 91, jdPreview: "", critiqueJson: null, pdfPath: null, applicationStatus: null, salaryMin: null, salaryMax: null, hasProgress: true },
      { jobId: 8, company: "Globex", title: "Product Lead", source: "indeed", location: "Remote", status: "applied", fitScore: 84, jdPreview: "", critiqueJson: null, pdfPath: null, applicationStatus: "submitted", salaryMin: null, salaryMax: null, hasProgress: true },
    ],
    pagination: { page: 1, pageSize: 200, totalItems: 2, totalPages: 1 },
    facets: {},
    total: 2,
  } }));
  await page.route("**/api/jobs/7", (route) => route.fulfill({ json: { id: 7, resumeVersions: [] } }));
}

test.beforeEach(async ({ page }) => { await mockCareerLab(page); });

test("Career Lab keeps setup and reference context out of the starter", async ({ page }) => {
  await page.goto("/career-lab");
  await expect(page.getByRole("heading", { name: "Career Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create Career Lab session" })).toBeVisible();
  await expect(page.getByText("Session setup")).toHaveCount(0);
  await expect(page.getByText("Reference context")).toHaveCount(0);
});

test("Career Lab does not overflow a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/career-lab");
  await expect(page.getByRole("heading", { name: "Career Lab" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("Career Lab reveals live reference filters only for an active session", async ({ page }) => {
  await page.unrouteAll();
  await mockCareerLab(page, true);
  await page.goto("/career-lab");
  await expect(page.getByText("Session setup")).toBeVisible();
  await expect(page.getByText("Reference context")).toBeVisible();
  await page.getByText("Job and resume context").click();
  await page.getByRole("combobox", { name: "Job source" }).selectOption("linkedin");

  const job = page.getByRole("combobox", { name: "Job", exact: true });
  await expect(job.getByRole("option", { name: /Acme · Staff Engineer/ })).toHaveCount(1);
  await expect(job.getByRole("option", { name: /Globex · Product Lead/ })).toHaveCount(0);
  await job.selectOption("7");
  await expect(job).toHaveValue("7");
  await page.getByLabel("Find a job").fill("Globex");
  await expect(job).toHaveValue("");
  await expect(job.getByRole("option", { name: /Acme · Staff Engineer/ })).toHaveCount(0);
  await expect(job.getByRole("option", { name: /Globex · Product Lead/ })).toHaveCount(1);
  await expect(page.getByRole("combobox", { name: "Job status" }).getByRole("option", { name: "applied" })).toHaveCount(1);
  await expect(page.getByRole("combobox", { name: "Job status" }).getByRole("option", { name: "tailored" })).toHaveCount(0);
});
