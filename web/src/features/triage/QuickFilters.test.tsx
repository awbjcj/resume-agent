import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QuickFilters } from "./QuickFilters";

describe("QuickFilters", () => {
  it("applies the low-fit preset", () => {
    const onApply = vi.fn();
    render(<QuickFilters onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: /low-fit/i }));
    expect(onApply).toHaveBeenCalledWith({ maxFit: 40 });
  });
});
