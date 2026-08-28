import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgendaRail } from "./AgendaRail";

describe("AgendaRail", () => {
  it("puts the current question first and maps topic states to user-facing labels", () => {
    render(
      <AgendaRail
        currentQuestion="What changed after launch?"
        currentTopicId="current"
        topics={[
          { id: "upcoming", gap: "Show leadership", whyItMatters: "Scope needs evidence.", relatedRef: "", ownerId: "", status: "open", noteDocId: null },
          { id: "fulfilled", gap: "Quantify impact", whyItMatters: "Metrics strengthen the claim.", relatedRef: "", ownerId: "", status: "drafted", noteDocId: null },
          { id: "current", gap: "Clarify business impact", whyItMatters: "Outcomes make the work credible.", relatedRef: "", ownerId: "", status: "open", noteDocId: null },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("What changed after launch?");
    expect(items[0]).toHaveTextContent("In progress");
    expect(screen.getByRole("listitem", { current: "step" })).toBe(items[0]);
    expect(items[1]).toHaveTextContent("Upcoming");
    expect(items[2]).toHaveTextContent("Fulfilled");
    expect(screen.getByRole("heading", { name: "Evidence path" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Evidence path" })).toHaveClass(
      "overflow-y-auto",
    );
  });
});
