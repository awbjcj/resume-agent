import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineDetails } from "./PipelineDetails";

describe("PipelineDetails", () => {
  it("prioritizes the filtered reason", () => {
    render(
      <PipelineDetails
        row={{
          status: "filtered",
          rejectReason: "salary below minimum",
          rejectCategory: "filtered",
          employmentType: "full_time",
        }}
      />,
    );

    expect(screen.getByLabelText("Filtered: salary below minimum")).toBeInTheDocument();
    expect(screen.queryByText("Full Time")).not.toBeInTheDocument();
  });

  it("shows compact metadata when no rejection reason exists", () => {
    render(
      <PipelineDetails
        row={{
          status: "approved",
          salaryMin: 140000,
          salaryMax: 180000,
          salaryCurrency: "USD",
          seniority: "staff",
          employmentType: "full_time",
          remotePolicy: "hybrid",
          sponsorshipSignal: "offered",
        }}
      />,
    );

    expect(screen.getByLabelText("Pipeline details")).toBeInTheDocument();
    expect(screen.getByText("$140k–180k")).toBeInTheDocument();
    expect(screen.getByText("Full Time")).toBeInTheDocument();
    expect(screen.getByText("Offered")).toBeInTheDocument();
  });
});
