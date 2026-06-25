import { render, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { emptyFilterState } from "@/lib/filters/types";

describe("FilterDesk min-fit slider", () => {
  it("emits a numeric fitMin when the slider is driven by keyboard", () => {
    const onChange = vi.fn();
    const { container } = render(
      <FilterDesk filter={emptyFilterState()} facets={{}} total={0} onChange={onChange} />,
    );

    // base-ui drives value changes through its hidden native range input.
    const input = container.querySelector('input[type="range"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.change(input, { target: { value: "1" } });

    expect(onChange).toHaveBeenCalled();
    const patch = onChange.mock.calls.at(-1)![0];
    // Guards the value plumbing: base-ui emits the array shape, the handler must
    // unwrap [0] to a numeric fitMin (not null). The display bug was CSS — the
    // missing data-horizontal variant collapsed the track — but this protects
    // the handler from regressing once the slider is interactable again.
    expect(patch.fitMin).toBe(1);
  });
});
