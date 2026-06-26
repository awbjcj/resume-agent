import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { emptyFilterState } from "@/lib/filters/types";

describe("FilterDesk min-fit slider", () => {
  it("keeps slider movement local until filters are applied", () => {
    const onChange = vi.fn();
    const { container } = render(
      <FilterDesk filter={emptyFilterState()} facets={{}} total={0} onChange={onChange} />,
    );

    // base-ui drives value changes through its hidden native range input.
    const input = container.querySelector('input[type="range"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.change(input, { target: { value: "1" } });

    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /apply filters/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const patch = onChange.mock.calls.at(-1)![0];
    expect(patch.fitMin).toBe(1);
  });
});
