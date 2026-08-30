import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

test.use({ locale: "zh-CN" });

const reviewConfig = {
  maxRounds: 3,
  scoreThreshold: 85,
  mergedAdvisory: false,
  evidencePortfolioEnabled: false,
  earlyStopOnRegression: false,
  tailorTier: "premium",
  reviserTier: "premium",
  provenanceRetryBudget: 1,
  styleGuidePath: "config/style_guide.md",
  reviewers: [
    { name: "fact-check", gate: true, weight: 0, modelTier: "premium", scoreBands: false },
    { name: "ats-keyword", gate: false, weight: 1, modelTier: "mid", scoreBands: true },
  ],
  lengthBudget: {
    pageTarget: 2,
    maxExperiences: 5,
    maxProjects: 4,
    maxEvidenceOwners: 8,
    minBulletsPerRole: 5,
    maxBulletsPerRole: 7,
    minBulletsPerProject: 4,
    maxBulletsPerProject: 6,
    targetTotalBullets: 40,
    minAspectsPerOwner: 3,
    targetSkills: 40,
    maxSkillsPerCategory: 12,
  },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/run-completions", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) =>
    route.fulfill({
      json: {
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: null, githubUsername: null },
        search: { configured: true },
        sources: { enabledCount: 1 },
        complete: true,
      },
    }),
  );
  await mockEmptyRuns(page);
  await page.route("**/api/config/review", async (route) => {
    const body = route.request().method() === "PUT" ? route.request().postDataJSON() : reviewConfig;
    await route.fulfill({ json: body });
  });
  await page.route("**/api/config/review-deep", async (route) => {
    const body = route.request().method() === "PUT" ? route.request().postDataJSON() : reviewConfig;
    await route.fulfill({ json: body });
  });
});

test("renders localized gates, tiers, and reviewer notes without altering model values", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/settings/review");

  await expect(page.getByText("硬性门槛", { exact: true })).toBeVisible();
  await expect(page.getByText(/启用硬性门槛的评审会直接阻断本轮/)).toBeVisible();
  await expect(page.getByText(/阻断项/)).toBeVisible();
  await expect(page.getByRole("button", { name: "写作模型档位：标准型" })).toBeVisible();
  await expect(page.getByRole("button", { name: "修订模型档位：高级型" })).toBeVisible();
  await expect(page.getByText("mid", { exact: true })).toHaveCount(0);
  await expect(page.getByText("premium", { exact: true })).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});
