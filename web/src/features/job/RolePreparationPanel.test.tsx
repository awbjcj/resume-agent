import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { RolePreparationPanel } from "./RolePreparationPanel";

const mocks = vi.hoisted(() => ({ trackRun: vi.fn() }));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const ready = {
  state: "ready",
  reason: null,
  canRefresh: true,
  inputsChanged: true,
  brief: {
    jobId: 42,
    company: "Acme",
    title: "Platform Engineer",
    generatedAt: "2026-08-30T12:00:00Z",
    inputFingerprint: "abc",
    companyIntelligenceVersionId: 7,
    companyIntelligenceVersionNumber: 2,
    resumeVersionId: 9,
    coverLetterId: null,
    applicationStatus: "interview",
    signalEventIds: [3],
    positioningSummary: "Lead with platform ownership.",
    competencies: [
      { name: "Platform ownership", rationale: "The role owns core services.", companyCitations: [] },
    ],
    likelyQuestions: [
      {
        question: "How have you improved a production platform?",
        questionType: "behavioral",
        competency: "Platform ownership",
        rationale: "The role owns core services.",
        companyCitations: [],
        storyPrompt: "Use the billing reliability example.",
      },
    ],
    concerns: [
      { concern: "Scale depth", preparation: "Quantify traffic and reliability gains.", companyCitations: [] },
    ],
    questionsToAsk: [
      { text: "How is platform ownership measured?", rationale: "Tests scope.", companyCitations: [] },
    ],
    recruiterVerificationQuestions: [
      { text: "Which interview stage comes next?", rationale: "Clarifies process.", companyCitations: [] },
    ],
    priorRoundFocus: ["Give a more concrete scaling example."],
    caveat: "Likely questions are planning aids.",
  },
};

describe("RolePreparationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("renders frozen inputs, questions, feedback focus, and stale-input notice", async () => {
    server.use(
      http.get("/api/jobs/42/role-preparation-brief", () => HttpResponse.json(ready)),
    );
    const { container } = render(<RolePreparationPanel jobId={42} />, { wrapper });

    expect(await screen.findByText("Lead with platform ownership.")).toBeInTheDocument();
    expect(screen.getByText("Company research v2")).toBeInTheDocument();
    expect(screen.getByText("Give a more concrete scaling example.")).toBeInTheDocument();
    expect(screen.getByText("How have you improved a production platform?")).toBeInTheDocument();
    expect(screen.getByText(/saved brief remains unchanged/i)).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
  });

  it("launches explicit generation from the empty state", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/jobs/42/role-preparation-brief", () =>
        HttpResponse.json({
          state: "empty",
          reason: "not_generated",
          canRefresh: true,
          inputsChanged: false,
          brief: null,
          message: "Generate a role-specific brief.",
        }),
      ),
      http.post("/api/jobs/42/role-preparation-brief/refreshes", () =>
        HttpResponse.json(
          { runId: "run-prep", kind: "rolePreparation", meta: { jobId: 42 } },
          { status: 202 },
        ),
      ),
    );
    render(<RolePreparationPanel jobId={42} />, { wrapper });

    const button = await screen.findByRole("button", { name: "Generate brief" });
    await user.click(button);

    await waitFor(() => expect(screen.getByRole("button", { name: "Preparing…" })).toBeDisabled());
    expect(mocks.trackRun).toHaveBeenCalledWith({ runId: "run-prep", kind: "rolePreparation" });
  });
});
