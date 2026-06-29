import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { JobDetail } from "@/features/job/use-job-detail";

import { JobMeta } from "./JobMeta";

describe("JobMeta", () => {
  it("renders one canonical readable Industry row", () => {
    const job = {
      industry: "Autonomous Driving",
      source: "manual",
    } as JobDetail;

    render(<JobMeta job={job} />);

    expect(screen.getByText("Industry")).toBeInTheDocument();
    expect(screen.getByText("Autonomous Driving")).toBeInTheDocument();
    expect(screen.queryByText("Sector")).not.toBeInTheDocument();
  });
});
