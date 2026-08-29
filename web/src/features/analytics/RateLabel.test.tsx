import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GREY_BELOW, SUPPRESS_BELOW, rateConfidence } from "./chart-theme";
import { RateLabel } from "./RateLabel";

describe("the small-sample rule", () => {
  it("uses the documented confidence thresholds", () => {
    expect(SUPPRESS_BELOW).toBe(3);
    expect(GREY_BELOW).toBe(10);
    expect(rateConfidence(2)).toBe("suppressed");
    expect(rateConfidence(9)).toBe("low");
    expect(rateConfidence(10)).toBe("ok");
  });

  it("always shows counts and n but suppresses an unsafe percentage", () => {
    render(<RateLabel count={1} total={2} />);
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/n=2/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("mutes low-confidence percentages and never divides by zero", () => {
    const { rerender } = render(<RateLabel count={2} total={5} />);
    expect(screen.getByText(/40%/)).toHaveClass("text-muted-foreground");
    rerender(<RateLabel count={0} total={0} />);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });
});
