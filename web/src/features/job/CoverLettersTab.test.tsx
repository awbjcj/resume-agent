import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ launch: vi.fn() }));

vi.mock("@/features/runs/use-launch-run", () => ({
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

import { useRunStore } from "@/lib/runs/store";
import { CoverLettersTab } from "./CoverLettersTab";
import type { CoverLetterItem } from "./CoverLetterRow";

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

const letter: CoverLetterItem = {
  id: 11,
  jobId: 3,
  factCheckPassed: true,
  origin: "draft",
  pdfPath: null,
  createdAt: "2026-08-11T00:00:00Z",
};

function seedGenerateRun(
  jobId: number,
  status: "running" | "succeeded",
  meta: Record<string, unknown> = { jobId },
) {
  useRunStore.getState().upsert({
    runId: "cl-run",
    kind: "coverLetter",
    status,
    percent: 0,
    phase: "Drafting",
    current: 0,
    total: 1,
    etaText: null,
    meta,
  });
}

describe("CoverLettersTab", () => {
  beforeEach(() => {
    useRunStore.setState({ runs: {} });
    mocks.launch.mockReset();
    mocks.launch.mockResolvedValue(true);
  });

  it("offers generation from the empty state and launches it once", async () => {
    const user = userEvent.setup();
    wrap(<CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />);

    expect(screen.getByText("No cover letter yet")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Generate cover letter" }),
    );

    expect(mocks.launch).toHaveBeenCalledTimes(1);
    expect(mocks.launch.mock.calls[0][0]).toBe("coverLetter");
    expect(mocks.launch.mock.calls[0][3]).toEqual({ jobId: 3 });
  });

  it("replaces the empty state with an in-progress placeholder while generating", () => {
    seedGenerateRun(3, "running");
    wrap(<CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />);

    expect(screen.getByText("Cover letter in progress")).toBeInTheDocument();
    expect(screen.queryByText("No cover letter yet")).toBeNull();
  });

  it("ignores a generate run belonging to another job", () => {
    seedGenerateRun(99, "running");
    wrap(<CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />);

    expect(screen.queryByText("Cover letter in progress")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Generate cover letter" }),
    ).toBeEnabled();
  });

  it("sees a bulk run that covers this job, so it cannot double-generate", () => {
    // The Pipeline bulk action tags runs with `jobIds`, not `jobId`. Missing that
    // shape offered Generate on a job already being generated for — and
    // POST /api/cover-letters has no singleton key, so it really runs twice.
    seedGenerateRun(3, "running", { jobIds: [3, 8] });
    wrap(<CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />);

    expect(screen.getByText("Cover letter in progress")).toBeInTheDocument();
    expect(screen.queryByText("No cover letter yet")).toBeNull();
  });

  it("ignores a bulk run that covers only other jobs", () => {
    seedGenerateRun(3, "running", { jobIds: [8, 9] });
    wrap(<CoverLettersTab jobId={3} coverLetters={[]} appliedId={null} />);

    expect(
      screen.getByRole("button", { name: "Generate cover letter" }),
    ).toBeEnabled();
  });

  it("offers another draft once a cover letter exists", () => {
    wrap(<CoverLettersTab jobId={3} coverLetters={[letter]} appliedId={null} />);

    expect(screen.queryByText("No cover letter yet")).toBeNull();
    expect(screen.getByRole("button", { name: "Generate another" })).toBeEnabled();
  });

  it("disables another draft while one is generating", () => {
    seedGenerateRun(3, "running");
    wrap(<CoverLettersTab jobId={3} coverLetters={[letter]} appliedId={null} />);

    // The busy label is prefixed by the Spinner's own "Loading" status text.
    expect(screen.getByRole("button", { name: /Generating…/ })).toBeDisabled();
  });
});
