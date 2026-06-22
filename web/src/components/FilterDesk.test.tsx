import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("reflects an active normalized skill as checked in the menu", async () => {
    // state.skills holds the normalized token 'go'; the option label is 'Go'.
    render(
      <FilterDesk
        rows={rows}
        state={{ ...emptyFilterState(), skills: new Set(["go"]) }}
        onChange={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /skills/i }));
    const item = await screen.findByRole("menuitemcheckbox", { name: "Go" });
    expect(item).toHaveAttribute("aria-checked", "true");
  });
});
