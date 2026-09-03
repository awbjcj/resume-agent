import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

const payload = {
  targetTotal: 1,
  clustersStale: false,
  categories: [
    { slug: "cloud-infrastructure", label: "Cloud & Infrastructure", kind: "hard" },
    { slug: "collaboration", label: "Collaboration", kind: "soft" },
  ],
  jobs: [
    {
      id: 1,
      company: "Acme",
      title: "Platform Engineer",
      seniority: "senior",
      status: "shortlisted",
    },
  ],
  skills: [{ key: "kubernetes", skill: "Kubernetes", domainId: "platform", covered: false, coverage: "gap", members: { Kubernetes: 1 }, must: 1, nice: 0, tech: 0, jobCount: 1 }],
  edges: [{ jobId: 1, skillKey: "kubernetes", skill: "Kubernetes", source: "must" }],
  domains: [{ id: "platform", label: "Platform engineering", category: "cloud-infrastructure", essentialScore: 3, popularScore: 1, jobCount: 1, skillCount: 1, gapCount: 1, adjacentCount: 0 }],
  suggestionStatuses: [],
};

async function mockMatchGap(page: import("@playwright/test").Page) {
  await mockEmptyRuns(page);
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: { secrets: { anthropicKey: true, anyLlmKey: true }, profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-07-18T00:00:00Z", githubUsername: null }, search: { configured: true }, sources: { enabledCount: 1 }, complete: true } }));
  await page.route(
    (url) => url.pathname === "/api/match-gap",
    (route) => route.fulfill({ json: payload }),
  );
}

test("drills from categories to domains and skills with accessible edit controls", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await mockMatchGap(page);

  await page.goto("/match-gap");
  await expect(page.getByRole("button", { name: "Explore Cloud & Infrastructure" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /select cloud & infrastructure/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Explore Cloud & Infrastructure" }).click();
  await page.getByRole("button", { name: "Explore Platform engineering" }).click();
  await expect(page.getByRole("button", { name: "Open Kubernetes details" })).toBeVisible();
  await expect(page.getByText("1 gaps")).toBeVisible();
  await page.getByRole("button", { name: "Add skill" }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Add skill" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("keeps match-gap filters and taxonomy actions contained on a narrow device", async ({ page }) => {
  await mockMatchGap(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/match-gap");

  const controls = page.getByRole("region", { name: "Dashboard controls" });
  await expect(controls).toHaveCSS("position", "static");

  const companyBox = await page.getByRole("combobox", { name: "Filter by company" }).boundingBox();
  const seniorityBox = await page.getByRole("combobox", { name: "Filter by seniority" }).boundingBox();
  expect(Math.abs((companyBox?.y ?? 0) - (seniorityBox?.y ?? 0))).toBeLessThanOrEqual(1);

  const stageBox = await page.getByRole("button", { name: "Stage" }).boundingBox();
  const gapsBox = await page.getByText("Gaps only", { exact: true }).locator("..").boundingBox();
  expect(Math.abs((stageBox?.y ?? 0) - (gapsBox?.y ?? 0))).toBeLessThanOrEqual(1);

  const actions = page.getByRole("group", { name: "Taxonomy actions" });
  const actionWidths = await actions.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(actionWidths.scrollWidth).toBeGreaterThan(actionWidths.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("keeps match-gap filters in document flow on desktop", async ({ page }) => {
  await mockMatchGap(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/match-gap");

  await expect(page.getByRole("region", { name: "Dashboard controls" })).toHaveCSS(
    "position",
    "static",
  );
});
