import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BoardSkeleton } from "./skeletons";

describe("BoardSkeleton", () => {
  it("is announced as busy to assistive tech", () => {
    render(<BoardSkeleton />);
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });
});
