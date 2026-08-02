import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CareerLabPage } from "./CareerLabPage";

const mocks = vi.hoisted(() => ({
  skills: vi.fn(),
  sessions: vi.fn(),
  session: vi.fn(),
  start: vi.fn(),
  send: vi.fn(),
  end: vi.fn(),
  archive: vi.fn(),
  unarchive: vi.fn(),
  remove: vi.fn(),
  stream: vi.fn(),
}));

vi.mock("./use-career-lab", () => ({
  useCareerLabSkills: () => mocks.skills(),
  useCareerLabSessions: () => mocks.sessions(),
  useCareerLabSession: () => mocks.session(),
  useStartCareerLab: () => mocks.start(),
  useSendCareerLabMessage: () => mocks.send(),
  useEndCareerLab: () => mocks.end(),
  useArchiveCareerLabSession: () => ({ mutate: mocks.archive }),
  useUnarchiveCareerLabSession: () => ({ mutate: mocks.unarchive }),
  useDeleteCareerLabSession: () => ({ mutate: mocks.remove, isPending: false }),
  useCareerLabRecoveredRun: () => null,
}));

vi.mock("@/lib/chat/useChatStream", () => ({
  useChatStream: () => mocks.stream(),
}));

function renderPage() {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(<CareerLabPage />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.skills.mockReturnValue({
    data: {
      skills: [
        {
          name: "salary-negotiation-prep",
          description: "Prepare a negotiation plan.",
          family: "career_lab",
          uses: ["career_lab"],
          isAvailable: true,
          unavailableReason: null,
        },
      ],
    },
    isPending: false,
  });
  mocks.sessions.mockReturnValue({ data: { sessions: [] }, isPending: false });
  mocks.session.mockReturnValue({ data: undefined, isPending: false });
  mocks.start.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.send.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.end.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.stream.mockReturnValue({ parts: [], status: "idle", error: null, stop: vi.fn(), reset: vi.fn() });
});

describe("CareerLabPage", () => {
  it("requires an explicit choice when routing is ambiguous", async () => {
    const mutateAsync = vi.fn().mockImplementation(async (input) => {
      input.onDone?.({
        runId: "run-1",
        kind: "career-lab-turn",
        status: "succeeded",
        percent: 100,
        phase: "done",
        current: 1,
        total: 1,
        etaText: null,
        result: { needsSelection: true, route: { reason: "Choose a skill" } },
      });
      return { runId: "run-1" };
    });
    mocks.start.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    await userEvent.type(screen.getByLabelText("Message Career Lab"), "Help with my career");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/choose a skill/i);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Career skill" })).toHaveFocus());
  });

  it("labels persisted responses as drafts and keeps the action surface draft-only", () => {
    mocks.sessions.mockReturnValue({
      data: { sessions: [{ sessionId: "s1", goal: "Plan", startedAt: "2026-08-02", endedAt: null, status: "active", archivedAt: null, turnCount: 2 }] },
      isPending: false,
    });
    mocks.session.mockReturnValue({
      data: {
        sessionId: "s1",
        goal: "Plan",
        startedAt: "2026-08-02",
        endedAt: null,
        status: "active",
        archivedAt: null,
        turns: [
          { turnId: "t1", role: "user", text: "Help", at: "2026-08-02", contextRefs: null, skillRef: null, agentMeta: null, artifact: null, notice: "" },
          { turnId: "t2", role: "assistant", text: "Here is a draft.", at: "2026-08-02", contextRefs: null, skillRef: { name: "salary-negotiation-prep", version: "2026-08-02", sha256: "a".repeat(64), family: "career_lab" }, agentMeta: null, artifact: { artifactType: "negotiation_plan", title: "Plan", summary: "Summary" }, notice: "" },
        ],
      },
      isPending: false,
    });
    renderPage();
    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /apply/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /upload/i })).not.toBeInTheDocument();
  });
});
