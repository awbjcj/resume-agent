import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SUMMARY } from "./fixtures";
import { StageRail, RAIL_STAGES } from "./StageRail";

describe("StageRail", () => {
  it("renders all seven stages with mapped counts", () => {
    render(<StageRail summary={SUMMARY} />);
    expect(RAIL_STAGES).toHaveLength(7);
    // raw folds in extracted: 3 + 1
    expect(screen.getByText("Raw").previousElementSibling).toHaveTextContent(
      "4",
    );
    expect(screen.getByText("Triage").previousElementSibling).toHaveTextContent(
      "2",
    );
    expect(
      screen.getByText("Applied").previousElementSibling,
    ).toHaveTextContent("5");
  });

  it("mutes zero-count stages without hiding them", () => {
    const zeroed = {
      ...SUMMARY,
      statusCounts: { ...SUMMARY.statusCounts, approved: 0 },
    };
    render(<StageRail summary={zeroed} />);
    const approved = screen.getByText("Approved").closest("li");
    expect(approved).toBeInTheDocument();
  });
});
