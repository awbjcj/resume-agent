import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { emptyFilterState } from "@/lib/filters/types";

describe("FilterDesk min-fit input", () => {
  it("pairs an exact numeric input with an accessible slider", () => {
    render(
      <FilterDesk filter={emptyFilterState()} facets={{}} total={0} onChange={vi.fn()} />,
    );

    expect(screen.getByRole("spinbutton", { name: "Min fit" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { hidden: true })).toHaveAttribute(
      "aria-label",
      "Minimum fit slider",
    );
  });

  it("keeps the numeric value local until filters are applied", () => {
    const onChange = vi.fn();
    render(
      <FilterDesk filter={emptyFilterState()} facets={{}} total={0} onChange={onChange} />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min fit" }), {
      target: { value: "65" },
    });

    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /apply filters/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const patch = onChange.mock.calls.at(-1)![0];
    expect(patch.fitMin).toBe(65);
  });
});
