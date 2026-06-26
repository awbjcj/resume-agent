import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/sources", (route) =>
    route.fulfill({
      json: [
        {
          id: "greenhouse:anthropic",
          kind: "greenhouse",
          type: "board",
          displayName: "Anthropic",
          enabled: true,
          pullable: true,
          detail: "anthropic",
        },
        {
          id: "remoteok",
          kind: "remoteok",
          type: "aggregator",
          displayName: "RemoteOK",
          enabled: true,
          pullable: true,
          detail: "aggregator",
        },
      ],
    }),
  );
});

test("sources page lists sections and add control", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByRole("heading", { name: /Boards & careers pages/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add source" })).toBeVisible();
});
