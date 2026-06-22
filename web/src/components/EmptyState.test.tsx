import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders a status region with title and body", () => {
    render(<EmptyState title="Nothing here" body="Run a pull to ingest jobs." />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText(/Run a pull/)).toBeInTheDocument();
  });
});
