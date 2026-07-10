import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";
import { FilterDesk } from "./FilterDesk";

describe("FilterDesk min-fit input", () => {
  it("pairs an exact numeric input with an accessible slider", () => {
    render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{}}
        total={0}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("spinbutton", { name: "Min fit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("slider", { hidden: true })).toHaveAttribute(
      "aria-label",
      "Minimum fit slider",
    );
    expect(screen.getByText("Min fit").parentElement).toHaveClass(
      "w-full",
      "sm:w-auto",
      "sm:min-w-36",
      "sm:flex-1",
    );
    expect(document.querySelector('[data-slot="slider"]')).toHaveClass(
      "min-w-0",
      "flex-1",
    );
  });

  it("keeps the numeric value local until filters are applied", () => {
    const onChange = vi.fn();
    render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{}}
        total={0}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min fit" }), {
      target: { value: "65" },
    });

    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const patch = onChange.mock.calls.at(-1)![0];
    expect(patch.fitMin).toBe(65);
  });

  it("keeps a slider change local until filters are applied", () => {
    const onChange = vi.fn();
    render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{}}
        total={0}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("slider", { hidden: true }), {
      target: { value: "72" },
    });

    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].fitMin).toBe(72);
  });

  it("clears applied fit and salary thresholds only when filters are applied", () => {
    const onChange = vi.fn();
    render(
      <FilterDesk
        filter={{ ...emptyFilterState(), fitMin: 65, salaryMin: 120000 }}
        facets={{}}
        total={0}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min fit" }), {
      target: { value: "" },
    });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Min salary (USD)" }),
      {
        target: { value: "" },
      },
    );

    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({
      fitMin: null,
      salaryMin: null,
    });
  });
});
