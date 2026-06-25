import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FacetPopover } from "./FacetPopover";

describe("FacetPopover", () => {
  it("filters options by the search box and toggles selection", () => {
    const onChange = vi.fn();
    render(
      <FacetPopover
        label="Skills"
        counts={{ python: 52, react: 38, go: 11 }}
        selected={new Set()}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Skills/ }));
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "rea" } });
    expect(screen.queryByText("python")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("react"));
    expect(onChange).toHaveBeenCalledWith(new Set(["react"]));
  });
});
