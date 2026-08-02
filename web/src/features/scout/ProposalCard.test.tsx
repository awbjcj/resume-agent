import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { ScoutProposal } from "./use-scout";

vi.mock("./use-scout", async (original) => ({ ...(await original()), useApproveScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }) }));
import { ProposalCard, proposalBadge } from "./ProposalCard";

const proposal = (overrides: Partial<ScoutProposal> = {}): ScoutProposal => ({ id: "p1", kind: "source", status: "pending", check: "validated", reason: "Strong platform fit", fitScore: 88, checkError: "", dismissReason: "", resolvedAt: null, citations: [{ url: "https://example.com/evidence", title: "Evidence" }], source: { company: "Acme", url: "https://jobs.example.com", ats: "greenhouse", roleCount: 4, token: "acme", errorCode: null }, term: null, ...overrides });

describe("ProposalCard", () => {
  it("applies status and validation badge precedence", () => {
    expect(proposalBadge(proposal({ status: "added", check: "failed" }))).toBe("Added");
    expect(proposalBadge(proposal({ status: "dismissed" }))).toBe("Dismissed");
    expect(proposalBadge(proposal())).toBe("4 roles");
    expect(proposalBadge(proposal({ check: "unverified" }))).toBe("Scrape target");
    expect(proposalBadge(proposal({ check: "duplicate" }))).toBe("Already in sources");
  });

  it("shows safe citations and an accessible bounded dismiss field", async () => {
    const user = userEvent.setup();
    const { container } = render(<ProposalCard sessionId="s1" proposal={proposal()} scrapeAvailable />);
    const link = screen.getByRole("link", { name: "Evidence" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    await user.click(screen.getByRole("button", { name: "Dismiss Acme" }));
    expect(screen.getByLabelText("Reason for dismissing Acme")).toHaveAttribute("maxlength", "200");
    expect((await axe(container)).violations).toEqual([]);
  });

  it("does not offer active controls for resolved or unsafe proposals", () => {
    const { rerender } = render(<ProposalCard sessionId="s1" proposal={proposal({ status: "added" })} scrapeAvailable />);
    expect(screen.queryByRole("button", { name: /add acme/i })).not.toBeInTheDocument();
    rerender(<ProposalCard sessionId="s1" proposal={proposal({ check: "failed" })} scrapeAvailable />);
    expect(screen.getByRole("button", { name: /add acme/i })).toBeDisabled();
    rerender(<ProposalCard sessionId="s1" proposal={proposal({ check: "new" })} scrapeAvailable />);
    expect(screen.getByRole("button", { name: /add acme/i })).toBeDisabled();
  });
});
