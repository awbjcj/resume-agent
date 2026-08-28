import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgendaRail } from "./AgendaRail";

describe("AgendaRail", () => {
  it("puts the current question first and maps topic states to user-facing labels", () => {
    render(
      <AgendaRail
        currentQuestion="You have already established the team size and delivery timeline. I considered several evidence paths, but only one matters now. Which business result changed after launch?"
        currentTopicId="current"
        topics={[
          { id: "upcoming", gap: "Show leadership", whyItMatters: "Scope needs evidence before the claim can be used, followed by internal explanation that should be compacted rather than shown in full to the user.", relatedRef: "", ownerId: "", status: "open", noteDocId: null },
          { id: "fulfilled", gap: "Quantify impact", whyItMatters: "Metrics strengthen the claim.", relatedRef: "", ownerId: "", status: "drafted", noteDocId: null },
          { id: "current", gap: "Clarify business impact", whyItMatters: "Outcomes make the work credible.", relatedRef: "", ownerId: "", status: "open", noteDocId: null },
        ]}
      />,
    );
    const evidencePath = screen.getByRole("region", { name: "Evidence path" });
    const current = within(evidencePath).getByRole("region", { current: "step" });
    expect(current).toHaveTextContent("Which business result changed after launch?");
    expect(current).toHaveTextContent("In progress");
    expect(current).not.toHaveTextContent("I considered several evidence paths");
    const items = within(evidencePath).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Upcoming");
    expect(items[0]).not.toHaveTextContent("shown in full to the user");
    expect(items[1]).toHaveTextContent("Fulfilled");
    expect(screen.getByText("2 open · 1 fulfilled")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evidence path" })).toBeInTheDocument();
    expect(evidencePath).toHaveClass("overflow-y-auto");
  });

  it("falls back to the final prompt instead of repeating prior coach commentary", () => {
    render(
      <AgendaRail
        currentQuestion="The scope is now clear. The delivery baseline is also captured. Share the measurable business outcome."
        currentTopicId="current"
        topics={[
          { id: "current", gap: "Clarify business impact", whyItMatters: "Outcomes make the work credible.", relatedRef: "", ownerId: "", status: "open", noteDocId: null },
        ]}
      />,
    );

    const current = screen.getByRole("region", { current: "step" });
    expect(current).toHaveTextContent("Share the measurable business outcome.");
    expect(current).not.toHaveTextContent("The delivery baseline is also captured");
  });
});
