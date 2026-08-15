import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { SourceVerificationActions } from "./SourceVerificationActions";
import type { ScoutProposal } from "./use-scout";

const proposal = (
  check: ScoutProposal["check"] = "unverified",
  ats: string | null = "lever",
): ScoutProposal => ({
  id: "p1",
  kind: "source",
  status: "pending",
  check,
  checkError: "",
  dismissReason: "",
  resolvedAt: null,
  manualConfirmation: null,
  citations: [],
  reason: "",
  fitScore: null,
  term: null,
  source: {
    company: "Acme",
    url: "https://jobs.lever.co/acme",
    requestedUrl: "https://acme.example/careers",
    canonicalBoardUrl: "https://jobs.lever.co/acme",
    ats,
    token: "acme",
    roleCount: null,
    errorCode: null,
    resolutionStatus: check === "conflict" ? "conflict" : "unverified",
    resolutionReason: check === "conflict" ? "ATS_CONFLICT" : "OWNERSHIP_NOT_PROVEN",
    evidence: [],
    searchedFamilies: ["lever"],
    unsearchedFamilies: ["workday"],
  },
});

describe("SourceVerificationActions", () => {
  it("offers an explicit, audited confirmation only after an affirmation", async () => {
    const user = userEvent.setup();
    const resolve = vi.fn().mockResolvedValue({});
    const confirm = vi.fn().mockResolvedValue({});
    const { container } = render(
      <SourceVerificationActions
        proposal={proposal()}
        scrapeAvailable={false}
        onResolve={resolve}
        onConfirm={confirm}
      />,
    );

    const board = screen.getByRole("link", { name: "Open board" });
    expect(board).toHaveAttribute("href", "https://jobs.lever.co/acme");
    expect(board).toHaveAttribute("target", "_blank");
    expect(board).toHaveAttribute("rel", "noreferrer");
    await user.click(screen.getByRole("button", { name: "Try another URL" }));
    const input = screen.getByLabelText("Board URL for Acme");
    await user.clear(input);
    await user.type(input, "https://jobs.lever.co/acme-careers");
    await user.click(screen.getByRole("button", { name: "Resolve URL" }));
    expect(resolve).toHaveBeenCalledWith("https://jobs.lever.co/acme-careers");

    await user.click(screen.getByRole("button", { name: "Confirm and add anyway" }));
    expect(screen.getByRole("alertdialog", { name: "Confirm unverified board" })).toBeInTheDocument();
    const action = screen.getByRole("button", { name: "Confirm and add" });
    expect(action).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "I manually confirmed this is Acme's official job board." }));
    expect(action).toBeEnabled();
    await user.click(action);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect((await axe(container)).violations).toEqual([]);
  });

  it("keeps retry available for a conflict but never permits a manual override", async () => {
    const user = userEvent.setup();
    render(
      <SourceVerificationActions
        proposal={proposal("conflict")}
        scrapeAvailable
        onResolve={vi.fn().mockResolvedValue({})}
        onConfirm={vi.fn().mockResolvedValue({})}
      />,
    );

    expect(screen.getByRole("button", { name: "Try another URL" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and add anyway" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try another URL" }));
    expect(screen.getByText("Ownership conflict")).toBeInTheDocument();
  });

  it("returns focus to the confirmation trigger when the warning is dismissed", async () => {
    const user = userEvent.setup();
    render(
      <SourceVerificationActions
        proposal={proposal()}
        scrapeAvailable
        onResolve={vi.fn().mockResolvedValue({})}
        onConfirm={vi.fn().mockResolvedValue({})}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Confirm and add anyway" });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(trigger).toHaveFocus();
  });

  it("does not offer a generic unverified board for manual confirmation without a browser", () => {
    render(
      <SourceVerificationActions
        proposal={proposal("unverified", null)}
        scrapeAvailable={false}
        onResolve={vi.fn().mockResolvedValue({})}
        onConfirm={vi.fn().mockResolvedValue({})}
      />,
    );

    expect(screen.getByRole("button", { name: "Try another URL" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and add anyway" })).not.toBeInTheDocument();
  });

  it("preserves a typed replacement URL and announces a resolution error", async () => {
    const user = userEvent.setup();
    render(
      <SourceVerificationActions
        proposal={proposal()}
        scrapeAvailable
        onResolve={vi.fn().mockRejectedValue(new Error("The board could not be resolved."))}
        onConfirm={vi.fn().mockResolvedValue({})}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Try another URL" }));
    const input = screen.getByLabelText("Board URL for Acme");
    await user.clear(input);
    await user.type(input, "https://acme.example/other-board");
    await user.click(screen.getByRole("button", { name: "Resolve URL" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The board could not be resolved.");
    expect(input).toHaveValue("https://acme.example/other-board");
  });
});
