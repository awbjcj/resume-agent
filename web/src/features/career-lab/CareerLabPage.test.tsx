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
  rename: vi.fn(),
  jobs: vi.fn(),
  jobDetail: vi.fn(),
  stream: vi.fn(),
  streamIds: [] as Array<string | null>,
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
  useRenameCareerLabSession: () => ({ mutateAsync: mocks.rename, isPending: false }),
  useCareerLabJobs: () => mocks.jobs(),
  useCareerLabJobDetail: () => mocks.jobDetail(),
  useCareerLabRecoveredRun: () => null,
}));

vi.mock("@/lib/chat/useChatStream", () => ({
  useChatStream: (runId: string | null) => {
    mocks.streamIds.push(runId);
    return mocks.stream();
  },
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
  mocks.streamIds.length = 0;
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
  mocks.jobs.mockReturnValue({ data: [], isPending: false, isError: false });
  mocks.jobDetail.mockReturnValue({ data: undefined, isPending: false, isError: false });
  mocks.start.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.send.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.end.mockReturnValue({ mutateAsync: vi.fn() });
  mocks.stream.mockReturnValue({ parts: [], status: "idle", error: null, stop: vi.fn(), reset: vi.fn() });
});

describe("CareerLabPage", () => {
  it("keeps the starter visible while the disabled session query reports pending", () => {
    mocks.session.mockReturnValue({ data: undefined, isPending: true });
    renderPage();

    expect(screen.getByRole("button", { name: "Create Career Lab session" })).toBeInTheDocument();
  });

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
    await userEvent.click(screen.getByRole("button", { name: "Create Career Lab session" }));
    await userEvent.type(screen.getByLabelText("Career Lab request"), "Help with my career");
    await userEvent.click(screen.getByRole("button", { name: "Start session" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/choose a skill/i);
    expect(screen.getByTestId("chat-viewport")).toHaveTextContent("Help with my career");
    expect(screen.getByTestId("chat-viewport")).toHaveTextContent("Choose a skill");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Career skill" })).toHaveFocus());
    await waitFor(() => expect(mocks.streamIds.at(-1)).toBeNull());
  });

  it("shows the initial thread while the session is being created", async () => {
    let resolveLaunch: ((value: { runId: string }) => void) | undefined;
    const launched = new Promise<{ runId: string }>((resolve) => {
      resolveLaunch = resolve;
    });
    const mutateAsync = vi.fn(() => launched);
    mocks.start.mockReturnValue({ mutateAsync, isPending: false });

    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Create Career Lab session" }));
    await userEvent.type(screen.getByLabelText("Career Lab request"), "Show me a draft");
    await userEvent.click(screen.getByRole("button", { name: "Start session" }));

    const viewport = screen.getByTestId("chat-viewport");
    expect(viewport).toHaveTextContent("Show me a draft");

    resolveLaunch?.({ runId: "run-1" });
  });

  it("shows immediate status while Career Lab waits for its first streamed reply", async () => {
    mocks.start.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({ runId: "run-1" }),
      isPending: false,
    });
    mocks.stream.mockReturnValue({
      parts: [],
      status: "streaming",
      error: null,
      stop: vi.fn(),
      reset: vi.fn(),
    });

    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Create Career Lab session" }));
    await userEvent.type(screen.getByLabelText("Career Lab request"), "Show me a draft");
    await userEvent.click(screen.getByRole("button", { name: "Start session" }));

    expect(await screen.findByText("Career Lab is thinking…")).toBeInTheDocument();
  });

  it("separates the starter controls from one responsive session history", () => {
    renderPage();

    expect(screen.getAllByText("Session history")).toHaveLength(1);
    expect(screen.getByText("Session setup")).toBeInTheDocument();
    expect(screen.getByText("Reference context")).toBeInTheDocument();
  });

  it("renames a saved thread from its session menu and has no archive toggle", async () => {
    mocks.sessions.mockReturnValue({
      data: { sessions: [{ sessionId: "s1", title: "Negotiation notes", goal: "Plan", startedAt: "2026-08-02", endedAt: null, status: "active", archivedAt: null, turnCount: 2 }] },
      isPending: false,
    });
    mocks.session.mockReturnValue({ data: { sessionId: "s1", title: "Negotiation notes", goal: "Plan", startedAt: "2026-08-02", endedAt: null, status: "active", archivedAt: null, turns: [] }, isPending: false });
    mocks.rename.mockResolvedValue({});
    renderPage();

    expect(screen.queryByRole("button", { name: "Toggle archived sessions" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Actions for Negotiation notes" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "Offer strategy");
    await userEvent.click(screen.getByRole("button", { name: "Save title" }));

    expect(mocks.rename).toHaveBeenCalledWith({ sessionId: "s1", title: "Offer strategy" });
  });

  it("selects jobs by name and narrows them by status and source", async () => {
    mocks.jobs.mockReturnValue({
      data: [
        { jobId: 7, company: "Acme", title: "Staff Engineer", status: "tailored", source: "linkedin", location: "New York" },
        { jobId: 8, company: "Globex", title: "Product Lead", status: "applied", source: "indeed", location: "Remote" },
      ],
      isPending: false,
      isError: false,
    });
    renderPage();

    await userEvent.click(screen.getByText("Job and resume context"));
    await userEvent.selectOptions(screen.getByLabelText("Job status"), "tailored");
    await userEvent.selectOptions(screen.getByLabelText("Job source"), "linkedin");
    expect(screen.getByRole("option", { name: /Acme · Staff Engineer/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Globex · Product Lead/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Job"), "7");
    expect(screen.getByLabelText("Job")).toHaveValue("7");
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
