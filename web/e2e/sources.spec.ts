import { test, expect } from "@playwright/test";

let configuredLimit = 10;

test.beforeEach(async ({ page }) => {
  configuredLimit = 10;
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/setup/status", (route) =>
    route.fulfill({
      json: {
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-06-01T00:00:00Z", githubUsername: null },
        search: { configured: true },
        sources: { enabledCount: 2 },
        complete: true,
      },
    }));
  await page.route("**/api/sources", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as { limit: number | null };
      configuredLimit = body.limit ?? 10;
      await route.fulfill({
        json: {
          id: "greenhouse:anthropic",
          kind: "greenhouse",
          type: "board",
          displayName: "Anthropic",
          enabled: true,
          pullable: true,
          detail: "anthropic",
          limit: body.limit,
        },
      });
      return;
    }
    await route.fulfill({
      json: [
        {
          id: "greenhouse:anthropic",
          kind: "greenhouse",
          type: "board",
          displayName: "Anthropic",
          enabled: true,
          pullable: true,
          detail: "anthropic",
          limit: configuredLimit,
        },
        {
          id: "remoteok",
          kind: "remoteok",
          type: "aggregator",
          displayName: "RemoteOK",
          enabled: true,
          pullable: true,
          detail: "aggregator",
          limit: null,
        },
      ],
    });
  });
});

test("sources page lists sections and add control", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByRole("heading", { name: /Boards & careers pages/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add source" })).toBeVisible();
});

test("source limit commits on blur", async ({ page }) => {
  await page.goto("/sources");
  const input = page.getByRole("spinbutton", {
    name: "Per-pull job limit for Anthropic",
  });
  await expect(input).toHaveValue("10");

  const patch = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      decodeURIComponent(new URL(request.url()).pathname).endsWith(
        "/api/sources/greenhouse:anthropic",
      ),
  );
  await input.fill("25");
  await input.blur();
  expect((await patch).postDataJSON()).toEqual({ limit: 25 });
  await expect(input).toHaveValue("25");
});
