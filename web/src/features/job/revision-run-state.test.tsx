import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { CoverLettersTab } from "./CoverLettersTab";
import { VersionRow } from "./VersionRow";

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

const version = {
  id: 5,
  jobId: 3,
  round: 1,
  reviewScore: 90,
  factCheckPassed: true,
  failedGates: [],
  critiqueJson: null,
  origin: "tailor",
  pdfPath: null,
  createdAt: "2026-07-13T00:00:00Z",
  hasEvidencePortfolio: false,
};

describe("revision lifecycle UI", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("shows both the row state and a pending resume placeholder", () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "revise",
      status: "running",
      percent: 10,
      phase: "Revising",
      current: 0,
      total: 1,
      etaText: null,
      meta: { versionId: 5, jobId: 3, instruction: "shorter" },
    });

    wrap(
      <>
        <ul><VersionRow jobId={3} version={version} appliedVersionId={null} /></ul>
        <CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />
      </>,
    );

    expect(screen.getByText("Revision in progress")).toBeInTheDocument();
    expect(screen.getByLabelText("Resume revision instruction")).toBeDisabled();
  });

  it("marks a completed child as just created", () => {
    useRunStore.getState().upsert({
      runId: "r2",
      kind: "revise",
      status: "succeeded",
      percent: 100,
      phase: "Done",
      current: 1,
      total: 1,
      etaText: null,
      result: { versionId: 5, jobId: 3 },
    });

    wrap(<ul><VersionRow jobId={3} version={version} appliedVersionId={null} /></ul>);

    expect(screen.getByText("Just created")).toBeInTheDocument();
  });
});
