import { expect, test, type Page } from "@playwright/test";

async function mockCareerLab(page: Page) {
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { username: null, role: null, authRequired: false } }));
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/transcribe/availability", (route) => route.fulfill({ json: { available: false } }));
  await page.route("**/api/runs?*", (route) => route.fulfill({ json: { data: [], pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 } } }));
  await page.route("**/api/interview/sessions", (route) => route.fulfill({ json: { sessions: [] } }));
  await page.route("**/api/interview/sessions?*", (route) => route.fulfill({ json: { sessions: [] } }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: { secrets: { anthropicKey: true, anyLlmKey: true }, profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-08-01T00:00:00Z", githubUsername: null }, search: { configured: true }, sources: { enabledCount: 1 }, complete: true } }));
  await page.route("**/api/career-lab/skills", (route) => route.fulfill({ json: { skills: [{ name: "salary-negotiation-prep", description: "Prepare negotiation points.", family: "career_lab", uses: ["career_lab"], isAvailable: true, unavailableReason: null }] } }));
  await page.route("**/api/career-lab/sessions?*", (route) => route.fulfill({ json: { sessions: [], pagination: { page: 1, pageSize: 20, totalItems: 0, totalPages: 0 } } }));
}

test.beforeEach(async ({ page }) => { await mockCareerLab(page); });

test("Career Lab is reachable and keeps skill selection keyboard-operable", async ({ page }) => {
  await page.goto("/career-lab");
  await expect(page.getByRole("heading", { name: "Career Lab" })).toBeVisible();
  const skill = page.getByRole("combobox", { name: "Career skill" });
  await skill.focus();
  await expect(skill).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(skill).toHaveValue("salary-negotiation-prep");
});

test("Career Lab does not overflow a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/career-lab");
  await expect(page.getByRole("heading", { name: "Career Lab" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
