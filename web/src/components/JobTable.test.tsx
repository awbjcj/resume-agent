import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobTable } from "./JobTable";

const rows = [
  { jobId: 1, company: "Acme", title: "Eng", fitScore: 22, source: "adzuna", status: "rejected" },
  { jobId: 2, company: "Globex", title: "PM", fitScore: 40, source: "lever", status: "rejected" },
];

describe("JobTable", () => {
  it("renders rows and toggles a row checkbox", () => {
    const onToggle = vi.fn();
    render(
      <JobTable
        rows={rows}
        selection={{ isSelected: () => false }}
        onToggle={onToggle}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Acme")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(onToggle).toHaveBeenCalled();
  });
});
