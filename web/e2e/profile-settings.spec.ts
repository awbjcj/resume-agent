import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

const setupStatus = {
  secrets: { anthropicKey: true, anyLlmKey: true },
  profile: {
    documentCount: 2,
    hasResume: true,
    factsBuiltAt: "2026-07-10T00:00:00Z",
    githubUsername: "octocat",
  },
  search: { configured: true },
  sources: { enabledCount: 1 },
  complete: true,
};

test.beforeEach(async ({ page }) => {
  let pythonGroup = "languages";
  let pythonGroupSource = "taxonomy";
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) => route.fulfill({ json: setupStatus }));
  await mockEmptyRuns(page);
  await page.route("**/api/profile/skeleton", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/profile/coach/sessions", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/profile/sources", (route) =>
    route.fulfill({
      json: [
        {
          id: "resume",
          filename: "resume.pdf",
          mode: "literal",
          origin: "upload",
          primary: true,
          anchor: null,
          addedAt: "2026-07-10T00:00:00Z",
          fragmentStatus: "cached",
        },
        {
          id: "github-repo",
          filename: "github--portfolio.md",
          mode: "project",
          origin: "github",
          primary: false,
          anchor: null,
          addedAt: "2026-07-10T00:00:00Z",
          fragmentStatus: "cached",
        },
      ],
    }));
  await page.route("**/api/profile/matrix", (route) =>
    route.fulfill({
      json: {
        generatedAt: "2026-07-10T00:00:00Z",
        groups: [
          { slug: "languages", label: "Languages" },
          { slug: "other", label: "Other" },
        ],
        rows: [
          {
            key: "python",
            display: "Python",
            category: "hard",
            group: pythonGroup,
            groupSource: pythonGroupSource,
            inferred: false,
            strength: 3,
            lastUsed: "current",
          },
          {
            key: "vflash",
            display: "vFlash",
            category: "hard",
            group: null,
            inferred: false,
            strength: 1,
            lastUsed: null,
          },
        ],
      },
    }));
  await page.route("**/api/profile/skills/*/group", async (route) => {
    if (route.request().method() === "PUT") {
      pythonGroup = route.request().postDataJSON().group;
      pythonGroupSource = "correction";
      await route.fulfill({
        json: {
          key: "python",
          display: "Python",
          category: "hard",
          group: pythonGroup,
          groupSource: pythonGroupSource,
          inferred: false,
          strength: 3,
          lastUsed: "current",
        },
      });
      return;
    }
    pythonGroup = "languages";
    pythonGroupSource = "taxonomy";
    await route.fulfill({ status: 204, body: "" });
  });
  await page.route("**/api/config/profile", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({ json: route.request().postDataJSON() });
      return;
    }
    await route.fulfill({
      json: {
        githubUsername: "octocat",
        githubRepoAllow: [],
        githubRepoDeny: [],
        githubRepoLimit: 20,
      },
    });
  });
  await page.route("**/api/profile/sources/note", (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: "note",
        filename: "note--on-call.md",
        mode: "literal",
        origin: "upload",
        primary: false,
        anchor: null,
        addedAt: "2026-07-10T00:00:00Z",
        fragmentStatus: "missing",
      },
    }));
});

test("profile depth controls and grouped skills form one working story", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Profile", exact: true })).toBeVisible();
  // Documents is the default tab — sources + repo controls live here.
  await expect(page.getByRole("row", { name: /github--portfolio\.md/i })).toContainText("GitHub");
  await expect(page.getByLabel("mode for github--portfolio.md")).toHaveCount(0);

  await page.getByRole("button", { name: "Add note" }).click();
  await page.getByLabel("Note title").fill("On-call");
  await page.getByLabel("Note text").fill("Led the rotation.");
  const noteRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/profile/sources/note") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "Save note" }).click();
  expect((await noteRequest).postDataJSON()).toEqual({ title: "On-call", text: "Led the rotation." });
  await expect(page.getByRole("dialog", { name: "Add a note" })).toHaveCount(0);

  await page.getByLabel("Always include repositories").fill("portfolio, flagship");
  await page.getByLabel("Exclude repositories").fill("archive");
  await page.getByLabel("Repository limit").fill("5");
  const saveRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/config/profile") && request.method() === "PUT",
  );
  await page.getByRole("button", { name: "Save changes" }).click();
  expect((await saveRequest).postDataJSON()).toMatchObject({
    githubRepoAllow: ["portfolio", "flagship"],
    githubRepoDeny: ["archive"],
    githubRepoLimit: 5,
  });

  // Skills are behind their own tab now, no longer stacked under Documents.
  await page.getByRole("tab", { name: "Skills" }).click();
  await expect(page.getByRole("heading", { name: "Skill groups" })).toBeVisible();
  await expect(page.getByText("Python", { exact: true })).toBeVisible();
  await expect(page.getByText("vFlash", { exact: true })).toBeVisible();

  const moveRequest = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/profile/skills/python/group") &&
      request.method() === "PUT",
  );
  await page.getByRole("button", { name: "Change group for Python" }).click();
  await page.getByRole("menuitem", { name: "Other", exact: true }).click();
  expect((await moveRequest).postDataJSON()).toEqual({ group: "other" });
  const pinnedTrigger = page.getByRole("button", { name: "Change group for Python" });
  await expect(pinnedTrigger.locator('[data-icon="inline-start"]')).toBeVisible();

  const resetRequest = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/profile/skills/python/group") &&
      request.method() === "DELETE",
  );
  await pinnedTrigger.click();
  await page.getByRole("menuitem", { name: "Reset to automatic" }).click();
  await resetRequest;
  await expect(
    page.getByRole("button", { name: "Change group for Python" }).locator(
      '[data-icon="inline-start"]',
    ),
  ).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test("profile settings stay contained at a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/profile");
  await page.getByRole("tab", { name: "Skills" }).click();
  await expect(page.getByRole("heading", { name: "Skill groups" })).toBeVisible();

  const layout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(layout.document).toBeLessThanOrEqual(layout.viewport);

  await page.getByRole("button", { name: "Add URL", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add a public page" });
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
});
