import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { emptyFilterState } from "@/lib/filters/types";

const facets = {
  country: { US: 1 },
  region: { NY: 1 },
  city: { "New York": 1 },
  skills: { go: 1 },
};

describe("FilterDesk", () => {
  it("renders the desk with a Min fit control", () => {
    render(<FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={() => {}} />);
    expect(screen.getByText("Min fit")).toBeInTheDocument();
    expect(screen.getByText("Sort")).toBeInTheDocument();
  });

  it("shows the Preset control only for composite sort", () => {
    const { rerender } = render(
      <FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={() => {}} />,
    );
    expect(screen.queryByText("Preset")).not.toBeInTheDocument();
    rerender(
      <FilterDesk
        filter={{ ...emptyFilterState(), sort: "composite" }}
        facets={facets}
        total={1}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("Preset")).toBeInTheDocument();
  });

  it("puts Status before the remaining primary controls when status facets exist", () => {
    render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{ ...facets, status: { new: 4 } }}
        total={4}
        onChange={() => {}}
      />,
    );

    const controls = [
      screen.getByRole("button", { name: "Status" }),
      screen.getByRole("spinbutton", { name: "Min fit" }),
      screen.getByRole("spinbutton", { name: "Min salary (USD)" }),
      screen.getByRole("combobox", { name: "Sort" }),
      screen.getByRole("searchbox", { name: "Search" }),
    ];

    controls.slice(1).forEach((control, index) => {
      expect(controls[index].compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING)
        .toBeTruthy();
    });
  });

  it("keeps only the most recently opened facet panel open", async () => {
    const user = userEvent.setup();
    render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{ ...facets, status: { new: 4 }, source: { greenhouse: 3 } }}
        total={4}
        onChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(screen.getByText("Filter by Status")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.queryByText("Filter by Status")).not.toBeInTheDocument();
    expect(screen.getByText("Filter by Source")).toBeInTheDocument();
  });

  it("does not reopen a facet that disappeared during a server refresh", async () => {
    const user = userEvent.setup();
    const filter = emptyFilterState();
    const onChange = vi.fn();
    const { rerender } = render(
      <FilterDesk
        filter={filter}
        facets={{ source: { greenhouse: 3 } }}
        total={3}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByText("Filter by Source")).toBeInTheDocument();

    rerender(<FilterDesk filter={filter} facets={{}} total={0} onChange={onChange} />);
    expect(screen.queryByText("Filter by Source")).not.toBeInTheDocument();

    rerender(
      <FilterDesk
        filter={filter}
        facets={{ source: { greenhouse: 3 } }}
        total={3}
        onChange={onChange}
      />,
    );
    expect(screen.queryByText("Filter by Source")).not.toBeInTheDocument();
  });

  it("renders the resolved industry name, not the SIC code", async () => {
    render(
      <FilterDesk
        filter={{ ...emptyFilterState(), industry: new Set(["07"]) }}
        facets={{ industry: { "07": 3 } }}
        total={3}
        onChange={() => {}}
      />,
    );
    // Active chip shows the resolved label, never the raw code.
    expect(screen.getByText("Agricultural Services")).toBeInTheDocument();
    expect(screen.queryByText("07")).not.toBeInTheDocument();
    // ...and so does the popover list.
    await userEvent.click(screen.getByRole("button", { name: /industry/i }));
    expect(await screen.findAllByText("Agricultural Services")).not.toHaveLength(0);
  });

  it("shows active normalized skills in the popover", async () => {
    render(
      <FilterDesk
        filter={{ ...emptyFilterState(), skills: new Set(["go"]) }}
        facets={facets}
        total={1}
        onChange={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /skills/i }));
    expect(await screen.findAllByText("go")).toHaveLength(2);
  });

  it("keeps search and salary drafts local until filters are applied", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={onChange} />);

    await user.type(screen.getByLabelText("Search"), "a");
    await user.type(screen.getByLabelText("Min salary (USD)"), "120000");

    expect(onChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /apply filters/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].q).toBe("a");
    expect(onChange.mock.calls[0][0].salaryMin).toBe(120000);
  });

  it("summarizes an annual salary draft and applies its numeric threshold", () => {
    const onChange = vi.fn();
    render(<FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={onChange} />);

    expect(screen.getByText("Any annual salary")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Min salary (USD)" }), {
      target: { value: "0" },
    });
    expect(screen.getByText("Any annual salary")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min salary (USD)" }), {
      target: { value: "1500" },
    });
    expect(screen.getByText("$1,500+ / year")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min salary (USD)" }), {
      target: { value: "120000" },
    });

    expect(screen.getByText("$120k+ / year")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /apply filters/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].salaryMin).toBe(120000);
  });

  it("marks a negative salary invalid and prevents applying the draft", () => {
    render(
      <FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "Min salary (USD)" }), {
      target: { value: "-1" },
    });

    expect(screen.getByText("Enter a non-negative annual salary.")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "Min salary (USD)" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("button", { name: /apply filters/i })).toBeDisabled();
  });
});
