import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const approve = vi.fn();
vi.mock("./use-scout", async (original) => ({ ...(await original()), useApproveScoutProposal: () => ({ mutateAsync: approve, isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }) }));
import { ProposalRail } from "./ProposalRail";
import type { ScoutProposal } from "./use-scout";

const base = (): Pick<ScoutProposal, "checkError" | "dismissReason" | "resolvedAt" | "citations" | "fitScore" | "reason"> =>
  ({ checkError: "", dismissReason: "", resolvedAt: null, citations: [], fitScore: 80, reason: "Fit" });

const source = (id: string, company: string, check: ScoutProposal["check"] = "validated"): ScoutProposal => ({
  ...base(), id, kind: "source", status: "pending", check,
  source: { company, url: `https://${company}.test`, ats: "greenhouse", roleCount: 1, token: company, errorCode: null }, term: null,
});

const term = (id: string, value: string, check: ScoutProposal["check"] = "new"): ScoutProposal => ({
  ...base(), id, kind: "search_term", status: "pending", check, source: null,
  term: { value, termKind: "keyword" },
});

const rows = ["one", "two", "three"].map((company, index) => source(`p${index + 1}`, company));

it("continues a sequential ready batch after a row fails", async () => {
  approve.mockReset().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("conflict")).mockResolvedValueOnce({});
  render(<ProposalRail sessionId="s1" proposals={rows} scrapeAvailable />);
  await userEvent.click(screen.getByRole("button", { name: "Add all ready proposals" }));
  expect(approve.mock.calls.map(([input]) => input.proposalId)).toEqual(["p1", "p2", "p3"]);
  expect(screen.getByText("2 added, 1 failed")).toBeInTheDocument();
  // The failure must be visible without expanding the row it belongs to.
  expect(screen.getByRole("alert")).toHaveTextContent("conflict");
  expect(screen.getByRole("alert")).toBeVisible();
});

it("enables the batch button for search terms, which are never probed into 'validated'", async () => {
  // The regression this replaces: the batch button required check === "validated",
  // but only source proposals are ever probed, so a turn of keywords left it dead.
  approve.mockReset().mockResolvedValue({});
  render(<ProposalRail sessionId="s1" proposals={[term("t1", "inference serving"), term("t2", "vector search")]} scrapeAvailable />);
  const button = screen.getByRole("button", { name: "Add all ready proposals" });
  expect(button).toBeEnabled();
  expect(button).toHaveTextContent("Add all ready (2)");
  await userEvent.click(button);
  expect(approve.mock.calls.map(([input]) => input.proposalId)).toEqual(["t1", "t2"]);
});

it("counts exactly the proposals whose own Add button is enabled", async () => {
  approve.mockReset().mockResolvedValue({});
  const proposals = [
    source("s-ok", "acme"),
    source("s-dup", "dupe", "duplicate"),
    source("s-fail", "broken", "failed"),
    source("s-scrape", "scrapeme", "unverified"),
    term("t-ok", "platform engineering"),
    term("t-dup", "already there", "duplicate"),
  ];
  render(<ProposalRail sessionId="s1" proposals={proposals} scrapeAvailable />);
  // acme + scrapeme (browser available) + platform engineering
  expect(screen.getByRole("button", { name: "Add all ready proposals" })).toHaveTextContent("Add all ready (3)");
  for (const [name, enabled] of [["Add acme", true], ["Add dupe", false], ["Add broken", false], ["Add scrapeme", true], ["Add platform engineering", true], ["Add already there", false]] as const) {
    expect(screen.getByRole("button", { name }), name)[enabled ? "toBeEnabled" : "toBeDisabled"]();
  }
});

it("drops unverified scrape targets from the batch when no browser is available", () => {
  render(<ProposalRail sessionId="s1" proposals={[source("s-ok", "acme"), source("s-scrape", "scrapeme", "unverified")]} scrapeAvailable={false} />);
  expect(screen.getByRole("button", { name: "Add all ready proposals" })).toHaveTextContent("Add all ready (1)");
  expect(screen.getByRole("button", { name: "Add scrapeme" })).toBeDisabled();
});

it("disables the batch button when nothing is ready", () => {
  render(<ProposalRail sessionId="s1" proposals={[source("s-dup", "dupe", "duplicate")]} scrapeAvailable />);
  const button = screen.getByRole("button", { name: "Add all ready proposals" });
  expect(button).toBeDisabled();
  expect(button).toHaveTextContent("Nothing ready to add");
});

it("groups companies, terms, and resolved rows into collapsible sections", async () => {
  const proposals = [
    source("s1", "acme"),
    term("t1", "platform engineering"),
    { ...source("s2", "gone"), status: "dismissed" as const },
  ];
  render(<ProposalRail sessionId="s1" proposals={proposals} scrapeAvailable />);
  expect(screen.getByRole("button", { name: /companies/i })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: /search terms/i })).toHaveAttribute("aria-expanded", "true");

  // Resolved starts collapsed so a long session's history cannot bury the work.
  const resolved = screen.getByRole("button", { name: /resolved/i });
  expect(resolved).toHaveAttribute("aria-expanded", "false");
  expect(within(resolved).getByText("1")).toBeInTheDocument();
  expect(screen.getByText("gone")).not.toBeVisible();
  await userEvent.click(resolved);
  expect(screen.getByText("gone")).toBeInTheDocument();
});

it("shows only an empty state when there are no proposals", () => {
  render(<ProposalRail sessionId="s1" proposals={[]} scrapeAvailable />);
  expect(screen.getByText("Proposals from your conversation will collect here.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /companies/i })).not.toBeInTheDocument();
});
