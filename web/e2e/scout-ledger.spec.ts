import { expect, test } from "@playwright/test";

import { mockEmptyRuns } from "./support";

/** The condition the redesign exists for: a ledger far past a handful of rows. */
const COMPANIES = [
  "Phinia", "Stripe", "Ramp", "Plaid", "Mercury", "Modal", "Anthropic", "Vercel",
  "Linear", "Retool", "Airbyte", "Databricks", "Snowflake", "Datadog",
];
const TERMS = [
  ["platform engineer", "role_anchor"], ["data engineer", "role_anchor"],
  ["inference serving", "keyword"], ["vector search", "keyword"],
  ["Senior Platform Engineer", "title"], ["intern", "exclude_term"],
  ["Remote", "location"], ["mid-senior", "seniority"],
] as const;

const proposals = [
  ...COMPANIES.map((company, index) => ({
    id: `s${index}`, kind: "source", status: "pending",
    check: index % 7 === 3 ? "unverified" : index % 11 === 5 ? "duplicate" : "validated",
    reason: `${company} runs a large platform organisation and is hiring into it; the board lists roles that match the standing goal.`,
    fitScore: 95 - index * 3, citations: [{ url: "https://example.com/e", title: "Careers" }],
    checkError: "", dismissReason: "", resolvedAt: null, term: null,
    source: {
      company,
      url: `https://job-boards.greenhouse.io/${company.toLowerCase()}`,
      requestedUrl: `https://job-boards.greenhouse.io/${company.toLowerCase()}`,
      canonicalBoardUrl: `https://job-boards.greenhouse.io/${company.toLowerCase()}`,
      ats: "greenhouse", token: company.toLowerCase(), roleCount: 4 + index, errorCode: null,
      resolutionStatus: index % 7 === 3 ? "unverified" : "verified",
      resolutionReason: index % 7 === 3 ? "OWNERSHIP_NOT_PROVEN" : "VERIFIED_PROVIDER_METADATA",
      evidence: [], searchedFamilies: ["greenhouse"], unsearchedFamilies: [],
    },
  })),
  ...TERMS.map(([value, termKind], index) => ({
    id: `t${index}`, kind: "search_term", status: "pending", check: "new",
    reason: `Adds precision to the title gate without narrowing the search beyond the standing goal.`,
    fitScore: null, citations: [], checkError: "", dismissReason: "", resolvedAt: null,
    source: null, term: { value, termKind },
  })),
  {
    id: "r0", kind: "source", status: "dismissed", check: "validated", reason: "Not a fit.",
    fitScore: 40, citations: [], checkError: "", dismissReason: "Wrong industry", resolvedAt: "2026-08-02T00:00:00Z",
    term: null, source: {
      company: "Acme", url: "https://job-boards.greenhouse.io/acme",
      requestedUrl: "https://job-boards.greenhouse.io/acme",
      canonicalBoardUrl: "https://job-boards.greenhouse.io/acme",
      ats: "greenhouse", token: "acme", roleCount: 2, errorCode: null,
      resolutionStatus: "verified", resolutionReason: "VERIFIED_PROVIDER_METADATA",
      evidence: [], searchedFamilies: ["greenhouse"], unsearchedFamilies: [],
    },
  },
];

const session = {
  sessionId: "sess-1", startedAt: "2026-08-02T00:00:00Z", endedAt: null, status: "active",
  archivedAt: null, goal: "Remote platform engineering roles at mid-size companies",
  turns: [
    { role: "user", kind: "", text: "Find remote platform roles at mid-size companies.", at: "2026-08-02T00:00:00Z", notice: "", proposalIds: [] },
    { role: "scout", kind: "reply", text: "I looked at fourteen companies with sizable platform organisations and pulled the search conditions that would surface those roles.", at: "2026-08-02T00:00:10Z", notice: "", proposalIds: [] },
  ],
  proposals, recap: null, scrapeAvailable: true, scrapeUnavailableReason: null,
};

test("the ledger stays bounded and grouped at twenty-plus proposals", async ({ page }) => {
  await mockEmptyRuns(page);
  // Registered list-first: Playwright matches routes in reverse registration
  // order, so the detail pattern must be added last to win for its own URL.
  await page.route("**/api/scout/sessions**", (route) => route.fulfill({ json: { sessions: [{ sessionId: "sess-1", startedAt: session.startedAt, endedAt: null, status: "active", archivedAt: null, goal: session.goal, proposalCount: proposals.length, pendingCount: proposals.length - 1, addedCount: 0, dismissedCount: 1 }] } }));
  await page.route("**/api/scout/sessions/sess-1**", (route) => route.fulfill({ json: session }));

  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/scout");

  const ledger = page.getByRole("complementary", { name: "Scout proposals" });
  await expect(ledger.getByRole("button", { name: /Companies/ })).toBeVisible();
  await expect(ledger.getByRole("button", { name: /Search terms/ })).toBeVisible();

  // The batch button is live and counts only what the rows themselves accept.
  const addAll = ledger.getByRole("button", { name: "Add all ready proposals" });
  await expect(addAll).toBeEnabled();

  // The point of the redesign: 22 proposals must not stretch the document.
  const { scrollHeight, clientHeight } = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  }));
  expect(scrollHeight - clientHeight).toBeLessThan(700);

  await page.screenshot({ path: "e2e/__screenshots__/scout-ledger-1920.png", fullPage: false });
});

test("an unverified board cannot be added until its URL resolves", async ({ page }) => {
  await mockEmptyRuns(page);
  const currentSession = structuredClone(session);
  let resolvedUrl = "";
  await page.route("**/api/scout/sessions**", (route) => route.fulfill({ json: { sessions: [{ sessionId: "sess-1", startedAt: session.startedAt, endedAt: null, status: "active", archivedAt: null, goal: session.goal, proposalCount: proposals.length, pendingCount: proposals.length - 1, addedCount: 0, dismissedCount: 1 }] } }));
  await page.route("**/api/scout/sessions/sess-1**", (route) => route.fulfill({ json: currentSession }));
  await page.route("**/api/scout/sessions/sess-1/proposals/s3/resolve", async (route) => {
    const body = route.request().postDataJSON() as { url: string };
    resolvedUrl = body.url;
    const plaid = currentSession.proposals.find((proposal) => proposal.id === "s3");
    if (!plaid?.source) throw new Error("expected Plaid source fixture");
    plaid.check = "validated";
    plaid.source = {
      ...plaid.source,
      url: body.url,
      requestedUrl: body.url,
      canonicalBoardUrl: body.url,
      ats: "workday",
      resolutionStatus: "verified",
      resolutionReason: "VERIFIED_FIRST_PARTY",
      searchedFamilies: ["workday"],
      unsearchedFamilies: [],
    };
    await route.fulfill({ json: currentSession });
  });

  await page.goto("/scout");
  const ledger = page.getByRole("complementary", { name: "Scout proposals" });
  await expect(ledger.getByRole("button", { name: "Add Plaid" })).toHaveCount(0);
  await expect(ledger.getByRole("button", { name: "Add all ready proposals" })).toHaveText(/\(19\)/);

  await ledger.getByRole("button", { name: "Plaid", exact: true }).click();
  await ledger.getByRole("button", { name: "Try another URL" }).click();
  const boardUrl = "https://plaid.wd5.myworkdayjobs.com/Plaid_Careers";
  await ledger.getByLabel("Board URL for Plaid").fill(boardUrl);
  await ledger.getByRole("button", { name: "Resolve URL" }).click();

  await expect(ledger.getByRole("button", { name: "Add Plaid" })).toBeVisible();
  expect(resolvedUrl).toBe(boardUrl);
});
