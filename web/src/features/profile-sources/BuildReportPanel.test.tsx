import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";

import { BuildReportPanel } from "./BuildReportPanel";

describe("BuildReportPanel", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("renders nothing without a completed build", () => {
    const { container } = render(<BuildReportPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows anchors, drops, and warnings from the run result", () => {
    useRunStore.getState().upsert({
      runId: "r1", kind: "profile-build", status: "succeeded",
      percent: 100, phase: "done", current: 3, total: 3, etaText: null,
      result: {
        experiences: 3, projects: 2,
        docStatus: { "resume-1": "cached", "deck-1": "extracted" },
        anchorDecisions: ["deck-1: +2 bullets on Acme/Engineer"],
        verificationDrops: ["deck-1: 'Cut latency 45%' — number '45%' not in source"],
        warnings: ["skill inference failed: boom"],
      },
    });
    render(<BuildReportPanel />);
    expect(screen.getByText(/deck-1: extracted/)).toBeInTheDocument();
    expect(screen.getByText(/\+2 bullets on Acme\/Engineer/)).toBeInTheDocument();
    expect(screen.getByText(/45%/)).toBeInTheDocument();
    expect(screen.getByText(/skill inference failed/)).toBeInTheDocument();
  });
});
