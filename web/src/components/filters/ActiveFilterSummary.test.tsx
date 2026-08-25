import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";

import { ActiveFilterSummary } from "./ActiveFilterSummary";

describe("ActiveFilterSummary", () => {
  it("renders a removable chip per active value and a match count", () => {
    const filter = emptyFilterState();
    filter.seniority = new Set(["senior"]);
    const onRemove = vi.fn();
    render(
      <ActiveFilterSummary
        filter={filter}
        total={1284}
        onRemove={onRemove}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByText(/1,284 matching/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /senior/i }));
    expect(onRemove).toHaveBeenCalledWith("seniority", "senior");
  });
});
