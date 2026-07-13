import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobTable } from "./JobTable";

const rows = [
  { jobId: 1, company: "Acme", title: "Eng", fitScore: 22, source: "greenhouse_jobs", location: "New York, NY", status: "rejected" },
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
    expect(screen.getByText("Greenhouse Jobs")).toBeInTheDocument();
    expect(screen.getByText("New York, NY")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(onToggle).toHaveBeenCalled();
  });

  it("renders an optional actions column without opening the row", () => {
    const onOpen = vi.fn();
    render(
      <JobTable
        rows={rows}
        selection={{ isSelected: () => false }}
        onToggle={vi.fn()}
        onOpen={onOpen}
        actions={(row) => <button type="button">Archive {row.jobId}</button>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Archive 1" }));
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });
});
