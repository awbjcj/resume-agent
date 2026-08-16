import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Progress } from "./progress";

describe("Progress", () => {
  it.each([
    [0, "scaleX(0)"],
    [42, "scaleX(0.42)"],
    [100, "scaleX(1)"],
    [140, "scaleX(1)"],
    [-10, "scaleX(0)"],
  ])("renders %s with clamped progress semantics", (value, transform) => {
    const { container } = render(<Progress value={value} aria-label="Completion" />);
    const clampedValue = Math.max(0, Math.min(100, value));
    expect(screen.getByRole("progressbar", { name: "Completion" })).toHaveAttribute(
      "aria-valuenow",
      String(clampedValue),
    );
    expect(container.querySelector('[data-slot="progress-indicator"]')).toHaveStyle({ transform });
  });
});
