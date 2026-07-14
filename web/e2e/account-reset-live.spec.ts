import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

test.skip(
  process.env.LIVE_RESET_E2E !== "1",
  "requires an isolated live reset API",
);

test("confirms and completes a profile reset through the live API", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.route("**/api/notifications", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      json: { username: "owner", role: "user", authRequired: false },
    }),
  );
  await mockEmptyRuns(page);
  await page.route("**/api/setup/status", (route) =>
    route.fulfill({
      json: {
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: {
          documentCount: 1,
          hasResume: true,
          factsBuiltAt: "2026-07-14T00:00:00Z",
          githubUsername: null,
        },
        search: { configured: true },
        sources: { enabledCount: 1 },
        complete: true,
      },
    }),
  );
  await page.route("**/api/account/usage", (route) =>
    route.fulfill({
      json: { weightedTotal: 0, ownKeyWeightedTotal: 0, budget: 0 },
    }),
  );
  await page.route("**/api/account/tokens", (route) =>
    route.fulfill({ json: { tokens: [] } }),
  );

  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
  await page.getByRole("button", { name: /profile sources/i }).click();
  await page.getByRole("button", { name: "Reset data" }).click();

  const dialog = page.getByRole("alertdialog", { name: /reset profile/i });
  await expect(dialog.getByRole("button", { name: "Export backup first" })).toBeVisible();
  const erase = dialog.getByRole("button", { name: "Erase selected data" });
  await expect(erase).toBeDisabled();
  await dialog.getByLabel(/type reset/i).fill("RESET");

  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/account/reset",
  );
  const navigationPromise = page.waitForEvent(
    "framenavigated",
    (frame) => frame === page.mainFrame(),
  );
  await erase.click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(new URL(response.url()).searchParams.get("confirm")).toBe("RESET");
  expect(response.request().postDataJSON()).toEqual({ scope: "profile" });
  await navigationPromise;
  await expect(page.getByText("Danger zone")).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});
