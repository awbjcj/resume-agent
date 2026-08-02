import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { ScoutProposal } from "./use-scout";

vi.mock("./use-scout", async (original) => ({ ...(await original()), useApproveScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }) }));
import { ProposalCard, proposalBadge } from "./ProposalCard";

// A row is an <li>: the rail renders it inside the section's <ul>, and axe
// rightly rejects a list item without a list parent.
const inList = (node: React.ReactNode) => <ul>{node}</ul>;

const proposal = (overrides: Partial<ScoutProposal> = {}): ScoutProposal => ({ id: "p1", kind: "source", status: "pending", check: "validated", reason: "Strong platform fit", fitScore: 88, checkError: "", dismissReason: "", resolvedAt: null, citations: [{ url: "https://example.com/evidence", title: "Evidence" }], source: { company: "Acme", url: "https://jobs.example.com", ats: "greenhouse", roleCount: 4, token: "acme", errorCode: null }, term: null, ...overrides });

describe("ProposalCard", () => {
  it("applies status and validation badge precedence", () => {
    expect(proposalBadge(proposal({ status: "added", check: "failed" }))).toBe("Added");
    expect(proposalBadge(proposal({ status: "dismissed" }))).toBe("Dismissed");
    expect(proposalBadge(proposal())).toBe("4 roles");
    expect(proposalBadge(proposal({ check: "unverified" }))).toBe("Scrape target");
    expect(proposalBadge(proposal({ check: "duplicate" }))).toBe("Already in sources");
  });

  it("keeps the row scannable and reveals evidence on demand", async () => {
    const user = userEvent.setup();
    const { container } = render(inList(<ProposalCard sessionId="s1" proposal={proposal()} scrapeAvailable />));
    // Collapsed: name and status badge only -- the reason and evidence are what
    // the disclosure reveals, so twenty rows stay scannable.
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("4 roles")).toBeInTheDocument();
    expect(screen.queryByText("Strong platform fit")).not.toBeVisible();
    const disclosure = screen.getByRole("button", { name: "Acme" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Evidence" })).not.toBeInTheDocument();

    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Strong platform fit")).toBeVisible();
    const link = screen.getByRole("link", { name: "Evidence" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect((await axe(container)).violations).toEqual([]);
  });

  it("opens the row when dismissing so the reason field is reachable", async () => {
    const user = userEvent.setup();
    render(inList(<ProposalCard sessionId="s1" proposal={proposal()} scrapeAvailable />));
    await user.click(screen.getByRole("button", { name: "Dismiss Acme" }));
    expect(screen.getByRole("button", { name: "Acme" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Reason for dismissing Acme")).toHaveAttribute("maxlength", "200");
  });

  it("does not offer active controls for resolved or unsafe proposals", () => {
    const { rerender } = render(inList(<ProposalCard sessionId="s1" proposal={proposal({ status: "added" })} scrapeAvailable />));
    expect(screen.queryByRole("button", { name: /add acme/i })).not.toBeInTheDocument();
    rerender(inList(<ProposalCard sessionId="s1" proposal={proposal({ check: "failed" })} scrapeAvailable />));
    expect(screen.getByRole("button", { name: /add acme/i })).toBeDisabled();
    rerender(inList(<ProposalCard sessionId="s1" proposal={proposal({ check: "new" })} scrapeAvailable />));
    expect(screen.getByRole("button", { name: /add acme/i })).toBeDisabled();
  });

  it("explains why a blocked proposal cannot be added", async () => {
    const user = userEvent.setup();
    render(inList(<ProposalCard sessionId="s1" proposal={proposal({ check: "unverified" })} scrapeAvailable={false} />));
    await user.click(screen.getByRole("button", { name: "Acme" }));
    expect(screen.getByText(/Browser scraping is unavailable/)).toBeInTheDocument();
  });
});
