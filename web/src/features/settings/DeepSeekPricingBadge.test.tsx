import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DeepSeekPricingBadge } from "./DeepSeekPricingBadge";

describe("DeepSeekPricingBadge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing before the peak/off-peak cutover", () => {
    vi.setSystemTime(new Date("2026-08-16T15:59:00Z"));
    const { container } = render(<DeepSeekPricingBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the off-peak state with a countdown to the next peak window", () => {
    vi.setSystemTime(new Date("2026-08-17T00:00:00Z"));
    render(<DeepSeekPricingBadge />);
    expect(screen.getByText("Off-peak")).toBeInTheDocument();
    expect(screen.getByText("· 1h")).toBeInTheDocument();
  });

  it("shows the peak state during a peak window", () => {
    vi.setSystemTime(new Date("2026-08-17T02:00:00Z"));
    render(<DeepSeekPricingBadge />);
    expect(screen.getByText("Peak")).toBeInTheDocument();
    expect(screen.getByText("· 2h")).toBeInTheDocument();
  });
});
