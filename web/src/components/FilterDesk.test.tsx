import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("Sort by")).toBeInTheDocument();
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
    await user.type(screen.getByLabelText(/min salary/i), "120000");

    expect(onChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /apply filters/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].q).toBe("a");
    expect(onChange.mock.calls[0][0].salaryMin).toBe(120000);
  });
});
