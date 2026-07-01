import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TriageCard } from "./TriageCard";
import type { TriageItem } from "./use-triage";

const row = (overrides: Partial<TriageItem> = {}): TriageItem => ({
  jobId: 1,
  company: "Acme",
  title: "Backend Engineer",
  location: "Remote",
  source: "greenhouse",
  status: "raw",
  fitScore: null,
  postedAt: null,
  archivedAt: null,
  hasProgress: false,
  ...overrides,
});

const noop = () => {};

describe("TriageCard", () => {
  it("shows the rejection reason for a rejected job", () => {
    render(
      <TriageCard
        row={row({ status: "rejected", rejectReason: "salary below minimum" })}
        checked={false}
        onCheck={noop}
        onOpen={noop}
      />,
    );
    expect(screen.getByText("salary below minimum")).toBeInTheDocument();
  });

  it("does not show a reason for a non-rejected job", () => {
    render(
      <TriageCard
        row={row({ status: "raw", rejectReason: "salary below minimum" })}
        checked={false}
        onCheck={noop}
        onOpen={noop}
      />,
    );
    expect(screen.queryByText("salary below minimum")).not.toBeInTheDocument();
  });
});
