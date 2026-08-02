import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgendaRail } from "./AgendaRail";

describe("AgendaRail", () => {
  it("marks the open topic as the current evidence step", () => {
    render(
      <AgendaRail topics={[
        { id: "open", gap: "Quantify impact", whyItMatters: "Metrics strengthen the claim.", relatedRef: "", status: "open", noteDocId: null },
        { id: "saved", gap: "Show leadership", whyItMatters: "Scope needs evidence.", relatedRef: "", status: "covered", noteDocId: "note-1" },
      ]} />,
    );
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Quantify impact");
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evidence path" })).toBeInTheDocument();
  });
});
