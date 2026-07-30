import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { AccountUsageCard } from "./AccountUsageCard";

const adminUsage = {
  weightedTotal: 12_400,
  ownKeyWeightedTotal: 820,
  budget: 0,
  costs: {
    sharedQuotaCostMicros: 2_500_000,
    byokEstimatedCostMicros: 750_000,
    toolCostMicros: 0,
    unpricedCallCount: 0,
  },
  sharedTokens: { inputTokens: 800, outputTokens: 200, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0, audioTokens: 0, totalTokens: 1_000 },
  byokTokens: { inputTokens: 300, outputTokens: 100, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0, audioTokens: 0, totalTokens: 400 },
};

describe("AccountUsageCard", () => {
  it("shows recorded costs and tokens for a quota-exempt administrator", async () => {
    const { container } = render(<AccountUsageCard usage={adminUsage} isAdmin />);

    expect(screen.getByText("No usage ceiling")).toBeInTheDocument();
    expect(screen.getByText("Shared-key spend")).toBeInTheDocument();
    expect(screen.getByText("$2.50")).toBeInTheDocument();
    expect(screen.getByText("BYOK estimated spend")).toBeInTheDocument();
    expect(screen.getByText("$0.75")).toBeInTheDocument();
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
  });
});
