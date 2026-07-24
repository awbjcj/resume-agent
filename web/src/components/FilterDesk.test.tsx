import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { salarySummary } from "./SalaryThresholdInput";
import { emptyFilterState } from "@/lib/filters/types";

const facets = {
  country: { US: 1 },
  region: { NY: 1 },
  city: { "New York": 1 },
  skills: { go: 1 },
};

describe("FilterDesk", () => {
  it.each([
    ["1000000", "$1M+ / year"],
    ["1500000", "$1.5M+ / year"],
  ])("formats an exact million salary %s as %s", (salary, summary) => {
    expect(salarySummary(salary)).toBe(summary);
  });

  it("renders the desk with a Min fit control", () => {
    render(<FilterDesk filter={emptyFilterState()} facets={facets} total={1} onChange={() => {}} />);
    expect(screen.getByText("Min fit")).toBeInTheDocument();
    expect(screen.getByText("Sort")).toBeInTheDocument();

    const searchField = screen.getByRole("searchbox", { name: "Search" })
      .closest('[data-slot="field"]');
    const fitField = screen.getByRole("spinbutton", { name: "Min fit" })
      .closest('[data-slot="field"]');
    expect(searchField?.parentElement).toBe(fitField?.parentElement);
    expect(searchField).toHaveClass("sm:flex-1");
    expect(fitField).toHaveClass("sm:flex-1");
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

  it("keeps the filter and sort controls in one ordered group", () => {
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
      screen.getByRole("searchbox", { name: "Search" }),
      screen.getByRole("spinbutton", { name: "Min fit" }),
      screen.getByRole("spinbutton", { name: "Min salary (USD)" }),
      screen.getByRole("combobox", { name: "Posted" }),
      screen.getByRole("combobox", { name: "Sort" }),
      screen.getByRole("button", { name: /^apply$/i }),
    ];

    controls.slice(1).forEach((control, index) => {
      expect(controls[index].compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING)
        .toBeTruthy();
    });
    expect(screen.getByRole("button", { name: /^apply$/i })).toHaveClass("sm:ml-auto");
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

  it("keeps an open facet option list stable during refreshes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <FilterDesk
        filter={emptyFilterState()}
        facets={{ source: { greenhouse: 1, lever: 1 } }}
        total={2}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByRole("checkbox", { name: /lever/i })).toBeInTheDocument();

    rerender(
      <FilterDesk
        filter={{ ...emptyFilterState(), source: new Set(["greenhouse"]) }}
        facets={{ source: { greenhouse: 1 } }}
        total={1}
        onChange={onChange}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /lever/i })).toBeInTheDocument();
  });

  it("renders the readable canonical in active chips and the popover", async () => {
    render(
      <FilterDesk
        filter={{ ...emptyFilterState(), industry: new Set(["Autonomous_Driving"]) }}
        facets={{ industry: { Autonomous_Driving: 3 } }}
        total={3}
        onChange={() => {}}
      />,
    );
    const label = "Autonomous Driving";
    expect(screen.getByText(label)).toBeInTheDocument();
    // ...and so does the popover list.
    await userEvent.click(screen.getByRole("button", { name: /industry/i }));
    expect(await screen.findAllByText(label)).not.toHaveLength(0);
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

    await user.click(screen.getByRole("button", { name: /^apply$/i }));

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

    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

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
    expect(screen.getByRole("button", { name: /^apply$/i })).toBeDisabled();
  });
});
