import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SUMMARY } from "./fixtures";
import { InsightsCard } from "./InsightsCard";

describe("InsightsCard", () => {
  it("shows practice progress and a healthy source state", () => {
    render(<InsightsCard summary={SUMMARY} />);

    expect(screen.getByText("3.8 / 5")).toBeInTheDocument();
    expect(screen.getByText("3 sessions completed")).toBeInTheDocument();
    expect(screen.getByText(/\+0\.8/)).toBeInTheDocument();
    expect(screen.getByText("All sources are healthy.")).toBeInTheDocument();
  });

  it("names affected sources when failures are open", () => {
    render(
      <InsightsCard
        summary={{
          ...SUMMARY,
          sourceHealth: {
            openFailures: 2,
            affectedSources: ["LinkedIn", "Indeed"],
            latestFailureAt: "2026-08-29T12:00:00Z",
          },
        }}
      />,
    );

    expect(screen.getByText("2 sources need attention")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn · Indeed")).toBeInTheDocument();
  });

  it("counts affected sources rather than failure records", () => {
    render(
      <InsightsCard
        summary={{
          ...SUMMARY,
          sourceHealth: {
            openFailures: 2,
            affectedSources: ["LinkedIn"],
            latestFailureAt: "2026-08-29T12:00:00Z",
          },
        }}
      />,
    );

    expect(screen.getByText("1 source needs attention")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: "p" })).toBeInTheDocument();
  });
});
