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
  it("renders field presentation as a compact full-width trigger", () => {
    render(
      <FacetPopover
        label="Skills"
        counts={counts}
        selected={new Set<string>()}
        onChange={vi.fn<(selected: Set<string>) => void>()}
        presentation="field"
      />,
    );

    expect(screen.getByRole("button", { name: "Skills" })).toHaveClass("h-9", "w-full");
  });

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

  it("disables Clear when no Skills are selected", () => {
    renderFacet();

    expect(screen.getByRole("button", { name: "Clear Skills filter" })).toBeDisabled();
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

  it("selects and deselects counted options", () => {
    const onChange = vi.fn<(selected: Set<string>) => void>();
    const props = {
      label: "Skills",
      counts,
      onChange,
      open: true,
      onOpenChange: vi.fn<(open: boolean) => void>(),
    };
    const { rerender } = render(
      <FacetPopover {...props} selected={new Set<string>()} />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /react/i }));
    expect(onChange).toHaveBeenLastCalledWith(new Set(["react"]));

    rerender(<FacetPopover {...props} selected={new Set(["react"])} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /react/i }));
    expect(onChange).toHaveBeenLastCalledWith(new Set());
  });

  it("refreshes its counts live while open (leave-one-out)", () => {
    const props = {
      label: "Skills",
      selected: new Set<string>(),
      onChange: vi.fn<(selected: Set<string>) => void>(),
      onOpenChange: vi.fn<(open: boolean) => void>(),
    };
    const { rerender } = render(
      <FacetPopover {...props} counts={{ python: 52, react: 38 }} open />,
    );
    expect(screen.getByText("52")).toBeInTheDocument();

    // The parent re-queried after another filter changed — the open popover
    // must reflect the new counts rather than a snapshot taken on open.
    rerender(<FacetPopover {...props} counts={{ python: 20, react: 9 }} open />);
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.queryByText("52")).not.toBeInTheDocument();
  });

  it("opens and closes from Done without controlled props", () => {
    render(
      <FacetPopover
        label="Skills"
        counts={counts}
        selected={new Set<string>()}
        onChange={vi.fn<(selected: Set<string>) => void>()}
      />,
    );

    expect(screen.queryByText("Filter by Skills")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /skills/i }));
    expect(screen.getByText("Filter by Skills")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Done filtering Skills" }));
    expect(screen.queryByText("Filter by Skills")).not.toBeInTheDocument();
  });

  it("resets search after a direct uncontrolled close and reopen", () => {
    render(
      <FacetPopover
        label="Skills"
        counts={counts}
        selected={new Set<string>()}
        onChange={vi.fn<(selected: Set<string>) => void>()}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Skills" });
    fireEvent.click(trigger);
    fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
      target: { value: "rea" },
    });

    fireEvent.click(trigger);
    fireEvent.click(trigger);

    expect(screen.getByPlaceholderText("Search skills...")).toHaveValue("");
    expect(screen.getByText("python")).toBeInTheDocument();
  });

  it("contains the popup while allowing only its option list to scroll", () => {
    renderFacet();

    const content = document.querySelector('[data-slot="popover-content"]');
    const command = document.querySelector('[data-slot="command"]');
    const list = document.querySelector('[data-slot="command-list"]');
    const header = document.querySelector('[data-slot="popover-header"]');
    const footer = screen.getByRole("button", { name: "Done filtering Skills" }).parentElement;

    expect(content).toHaveClass("max-h-[var(--available-height)]", "overflow-hidden");
    expect(command).toHaveClass("min-h-0", "flex-1");
    expect(list).toHaveClass("min-h-0", "flex-1", "overflow-y-auto");
    expect(header).toHaveClass("shrink-0");
    expect(footer).toHaveClass("shrink-0");
  });

  it("resets its search when a controlled parent closes it", () => {
    const props = {
      label: "Skills",
      counts,
      selected: new Set<string>(),
      onChange: vi.fn<(selected: Set<string>) => void>(),
      onOpenChange: vi.fn<(open: boolean) => void>(),
    };
    const { rerender } = render(<FacetPopover {...props} open />);

    fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
      target: { value: "rea" },
    });
    expect(screen.queryByText("python")).not.toBeInTheDocument();

    rerender(<FacetPopover {...props} open={false} />);
    rerender(<FacetPopover {...props} open />);

    expect(screen.getByPlaceholderText("Search skills...")).toHaveValue("");
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
    expect(screen.getByText("go")).toBeInTheDocument();
  });
});
