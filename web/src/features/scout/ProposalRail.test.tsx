import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const approve = vi.fn();
vi.mock("./use-scout", async (original) => ({ ...(await original()), useApproveScoutProposal: () => ({ mutateAsync: approve, isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }) }));
import { ProposalRail } from "./ProposalRail";
import type { ScoutProposal } from "./use-scout";

const rows = ["one", "two", "three"].map((company, index): ScoutProposal => ({ id: `p${index + 1}`, kind: "source", status: "pending", check: "validated", reason: "Fit", fitScore: 80, checkError: "", dismissReason: "", resolvedAt: null, citations: [], source: { company, url: `https://${company}.test`, ats: "greenhouse", roleCount: 1, token: company, errorCode: null }, term: null }));

it("continues a sequential validated batch after a row fails", async () => {
  approve.mockReset().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("conflict")).mockResolvedValueOnce({});
  render(<ProposalRail sessionId="s1" proposals={rows} scrapeAvailable />);
  await userEvent.click(screen.getByRole("button", { name: "Add all validated" }));
  expect(approve.mock.calls.map(([input]) => input.proposalId)).toEqual(["p1", "p2", "p3"]);
  expect(screen.getByText("2 added, 1 failed")).toBeInTheDocument();
  expect(screen.getByText("conflict")).toBeInTheDocument();
});
