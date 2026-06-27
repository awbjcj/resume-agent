import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, type Mock, vi } from "vitest";

import { FacetPopover } from "./FacetPopover";

const counts = { python: 52, react: 38, go: 11 };

function renderFacet({
  selected = new Set<string>(),
  onChange = vi.fn<(selected: Set<string>) => void>(),
  onOpenChange = vi.fn<(open: boolean) => void>(),
}: {
  selected?: Set<string>;
  onChange?: Mock<(selected: Set<string>) => void>;
  onOpenChange?: Mock<(open: boolean) => void>;
} = {}) {
  render(
    <FacetPopover
      label="Skills"
      counts={counts}
      selected={selected}
      onChange={onChange}
      open
      onOpenChange={onOpenChange}
    />,
  );

  return { onChange, onOpenChange };
}

describe("FacetPopover", () => {
  it("shows its controlled presentation and selected count", () => {
    renderFacet({ selected: new Set(["python"]) });

    expect(screen.getByText("Filter by Skills")).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  it("clears the selected Skills", () => {
    const { onChange } = renderFacet({ selected: new Set(["python"]) });

    fireEvent.click(screen.getByRole("button", { name: "Clear Skills filter" }));

    expect(onChange).toHaveBeenCalledWith(new Set());
  });

  it("closes from the Done action", () => {
    const { onOpenChange } = renderFacet();

    fireEvent.click(screen.getByRole("button", { name: "Done filtering Skills" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows a label-specific empty state while keeping Done available", () => {
    renderFacet();

    fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
      target: { value: "rust" },
    });

    expect(screen.getByText("No matching skills")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done filtering Skills" })).toBeInTheDocument();
  });
});
