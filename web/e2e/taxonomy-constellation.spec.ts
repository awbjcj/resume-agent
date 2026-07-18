import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

const payload = {
  targetTotal: 1,
  clustersStale: false,
  categories: [
    { slug: "cloud-infrastructure", label: "Cloud & Infrastructure", kind: "hard" },
    { slug: "collaboration", label: "Collaboration", kind: "soft" },
  ],
  jobs: [{ id: 1, company: "Acme", title: "Platform Engineer", seniority: "senior" }],
  skills: [{ key: "kubernetes", skill: "Kubernetes", domainId: "platform", covered: false, coverage: "gap", members: { Kubernetes: 1 }, must: 1, nice: 0, tech: 0, jobCount: 1 }],
  edges: [{ jobId: 1, skillKey: "kubernetes", skill: "Kubernetes", source: "must" }],
  domains: [{ id: "platform", label: "Platform engineering", category: "cloud-infrastructure", essentialScore: 3, popularScore: 1, jobCount: 1, skillCount: 1, gapCount: 1, adjacentCount: 0 }],
  suggestionStatuses: [],
};

test("drills from categories to domains and skills with accessible edit controls", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await mockEmptyRuns(page);
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: { secrets: { anthropicKey: true, anyLlmKey: true }, profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-07-18T00:00:00Z", githubUsername: null }, search: { configured: true }, sources: { enabledCount: 1 }, complete: true } }));
  await page.route("**/api/match-gap", (route) => route.fulfill({ json: payload }));

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
