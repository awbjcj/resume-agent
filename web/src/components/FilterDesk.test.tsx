import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FilterDesk } from "./FilterDesk";
import { emptyFilterState, type ShortlistItem } from "@/lib/filters/types";

const rows: ShortlistItem[] = [
  {
    jobId: 1,
    locationCountry: "US",
    locationRegion: "NY",
    locationCity: "New York",
    skills: [{ name: "Go", covered: false, required: true }],
  } as ShortlistItem,
];

describe("FilterDesk", () => {
  it("renders the desk with a Min fit control", () => {
    render(<FilterDesk rows={rows} state={emptyFilterState()} onChange={() => {}} />);
    expect(screen.getByText("Min fit")).toBeInTheDocument();
    expect(screen.getByText("Sort by")).toBeInTheDocument();
  });

  it("shows the Preset control only for composite sort", () => {
    const { rerender } = render(
      <FilterDesk rows={rows} state={emptyFilterState()} onChange={() => {}} />,
    );
    expect(screen.queryByText("Preset")).not.toBeInTheDocument();
    rerender(
      <FilterDesk
        rows={rows}
        state={{ ...emptyFilterState(), sort: "composite" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("Preset")).toBeInTheDocument();
  });
});
