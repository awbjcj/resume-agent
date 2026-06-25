import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BulkActionBar } from "./BulkActionBar";

describe("BulkActionBar", () => {
  it("offers select-all-matching only when all loaded rows are selected", () => {
    const props = {
      isAllMatching: false,
      pageCount: 50,
      total: 120,
      onSelectAllMatching: vi.fn(),
      onClear: vi.fn(),
      children: null,
    };
    const { rerender } = render(<BulkActionBar {...props} count={1} />);
    expect(screen.queryByText(/Select all 120/)).not.toBeInTheDocument();
    rerender(<BulkActionBar {...props} count={50} />);
    expect(screen.getByText(/Select all 120/)).toBeInTheDocument();
  });
});
