import { expect, test, type Page } from "@playwright/test";

const activeInterview = {
  sessionId: "s1", jobId: 7, resumeVersionId: 3, company: "Acme", title: "Engineer",
  startedAt: "2026-07-18T12:00:00Z", endedAt: null, status: "active",
  askedCount: 2, questionCount: 4, overallScore: null, archivedAt: null,
};

async function mockApp(page: Page) {
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { username: null, role: null, authRequired: false } }));
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/transcribe/availability", (route) => route.fulfill({ json: { available: false } }));
  await page.route("**/api/runs?*", (route) => route.fulfill({ json: { data: [], pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 } } }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: { secrets: { anthropicKey: true, anyLlmKey: true }, profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-06-01T00:00:00Z", githubUsername: null }, search: { configured: true }, sources: { enabledCount: 1 }, complete: true } }));
  await page.route("**/api/dashboard/summary", (route) => route.fulfill({ json: { statusCounts: { tailored: 1 }, queues: { triage: 0, approve: 0, tailor: 0, apply: 0 }, applied: 0, openErrorCount: 1, activeInterviews: [activeInterview], activeCoachSession: null } }));
  await page.route("**/api/errors?*", (route) => route.fulfill({ json: { records: [{ id: 1, kind: "source", sourceLabel: "Acme careers", message: "HTTP 403", count: 3, firstSeenAt: "2026-07-18T11:00:00Z", lastSeenAt: "2026-07-18T12:00:00Z", status: "open", runId: null }] } }));
  await page.route("**/api/errors/1/resolve", (route) => route.fulfill({ json: { ok: true } }));
  await page.route("**/api/interview/sessions/s1", (route) => route.fulfill({ json: { ...activeInterview, concluded: false, style: { stage: "technical", demeanor: "neutral", difficulty: "standard", questionCount: 4, extra: "" }, progress: { asked: 2, total: 4 }, plan: null, turns: [{ role: "interviewer", text: "Tell me about a difficult project.", questionId: "q1", isFollowup: false, at: "2026-07-18T12:01:00Z" }], debrief: null } }));
  await page.route("**/api/interview/sessions*", (route) => route.fulfill({ json: { sessions: [activeInterview] } }));
  await page.route("**/api/profile/coach/sessions/c1", (route) => route.fulfill({ json: { sessionId: "c1", status: "ended", startedAt: "2026-07-17T12:00:00Z", endedAt: "2026-07-17T13:00:00Z", archivedAt: null, recap: "You documented a measurable delivery outcome.", impact: null, topics: [], turns: [{ role: "coach", text: "What changed?", topicId: "t1", kind: "question", at: "2026-07-17T12:01:00Z", researchActions: [] }], draftNotes: [] } }));
  await page.route("**/api/profile/coach/sessions*", (route) => route.fulfill({ json: { sessions: [{ sessionId: "c1", status: "ended", startedAt: "2026-07-17T12:00:00Z", endedAt: "2026-07-17T13:00:00Z", topicCount: 1, savedNoteCount: 1, archivedAt: null }] } }));
}

test.beforeEach(async ({ page }) => { await mockApp(page); });

test("dashboard attention and in-progress cards lead into the interview hub", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("In progress", { exact: true })).toBeVisible();
  await expect(page.getByText("Acme · Engineer", { exact: true })).toBeVisible();
  await expect(page.getByText(/seen 3×/)).toBeVisible();
  await page.getByRole("button", { name: "Resolve" }).click();
  await page.getByRole("link", { name: "Resume Acme · Engineer" }).click();
  await expect(page).toHaveURL(/\/interview\?session=s1/);
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  await expect(page.getByText("Tell me about a difficult project.")).toBeVisible();
});

test("session management remains aligned at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/interview?session=s1");
  await expect(page.getByRole("button", { name: "New interview" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Actions for Acme · Engineer" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

  await page.goto("/coach");
  await expect(page.getByRole("heading", { name: "Past sessions" })).toBeVisible();
  await expect(page.getByRole("switch", { name: "Show archived" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Actions for coaching session c1/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
