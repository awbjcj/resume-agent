import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoachPage } from "./CoachPage";

const cancelRun = vi.hoisted(() => vi.fn());
vi.mock("@/features/runs/use-launch-run", () => ({ cancelRun }));

class FakeEventSource {
  static last: FakeEventSource | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeEventSource.last = this;
  }
  close() {}
  send(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}
vi.stubGlobal("EventSource", FakeEventSource);

const sendMessage = vi.fn();
const endSession = vi.fn();
const saveNote = vi.fn();
const discardNote = vi.fn();
const archiveSession = vi.fn();
const unarchiveSession = vi.fn();
const deleteSession = vi.fn();
const coachState = vi.hoisted(() => ({
  status: "active",
  recap: null as string | null,
  includeArchived: false,
  useDefaultSession: true,
  sessions: [] as Array<Record<string, unknown>>,
}));

vi.mock("@/components/TranscribeButton", () => ({ TranscribeButton: () => null }));

vi.mock("./use-coach", () => ({
  useCoachSessions: (includeArchived = false) => {
    coachState.includeArchived = includeArchived;
    return ({
    data: {
      sessions: coachState.sessions.length || coachState.useDefaultSession ? coachState.sessions.length ? coachState.sessions : [
        {
          sessionId: "session-1",
          status: coachState.status,
          startedAt: "2026-07-15T12:00:00Z",
          endedAt: null,
          topicCount: 1,
          savedNoteCount: 0,
        },
      ] : [],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
  },
  useCoachSession: (sessionId: string | null) => ({
    data: sessionId ? {
      sessionId: "session-1",
      status: coachState.status,
      startedAt: "2026-07-15T12:00:00Z",
      endedAt: null,
      recap: coachState.recap,
      impact: null,
      topics: [
        {
          id: "topic-1",
          gap: "Missing outcome",
          whyItMatters: "Hiring teams need evidence.",
          relatedRef: "experience-1",
          status: "open",
          noteDocId: null,
        },
      ],
      turns: [
        {
          role: "coach",
          text: "What changed after you shipped it?",
          topicId: "topic-1",
          kind: "question",
          at: "2026-07-15T12:00:01Z",
          researchActions: [],
        },
      ],
      draftNotes: [
        {
          topicId: "topic-1",
          title: "Improved delivery",
          summary: "Shipped a measurable improvement.",
          quotes: ["Cut delivery time by 30%."],
          status: "pending",
        },
      ],
    } : undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useStartCoachSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSendCoachMessage: () => ({ mutateAsync: sendMessage, isPending: false }),
  useEndCoachSession: () => ({ mutateAsync: endSession, isPending: false }),
  useSaveCoachNote: () => ({ mutateAsync: saveNote, isPending: false }),
  useDiscardCoachNote: () => ({ mutateAsync: discardNote, isPending: false }),
  useArchiveCoachSession: () => ({ mutate: archiveSession }),
  useUnarchiveCoachSession: () => ({ mutate: unarchiveSession }),
  useDeleteCoachSession: () => ({ mutate: deleteSession, isPending: false }),
  useRenameCoachSession: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("CoachPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    coachState.status = "active";
    coachState.recap = null;
    coachState.includeArchived = false;
    coachState.useDefaultSession = true;
    coachState.sessions = [];
    FakeEventSource.last = null;
    localStorage.setItem("resume-tailor-harness-token", "token");
    sendMessage.mockImplementation(async ({ onDone }) => {
      onDone?.({ status: "succeeded" });
      return { runId: "run-1" };
    });
  });

  it("renders the active coaching thread and agenda", () => {
    render(<CoachPage />);

    expect(screen.getByRole("heading", { name: "Profile Coach" })).toBeInTheDocument();
    expect(screen.getAllByText("What changed after you shipped it?")).toHaveLength(2);
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText(/Missing outcome/)).toBeInTheDocument();
    expect(screen.getByText("Improved delivery")).toBeInTheDocument();
    expect(screen.getByText("Active · 1 topic · 0 saved")).toBeInTheDocument();
  });

  it("uses the shared guided starting state when there is no active session", () => {
    coachState.useDefaultSession = false;
    render(<CoachPage />);

    expect(screen.getByText("Find the evidence your profile is missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start coaching session" })).toBeInTheDocument();
    expect(screen.queryByText("What changed after you shipped it?")).not.toBeInTheDocument();
  });

  it("preserves a message until its run succeeds", async () => {
    const user = userEvent.setup();
    render(<CoachPage />);

    const composer = screen.getByLabelText("Message your Profile Coach");
    await user.type(composer, "It reduced cycle time by 30%.");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        message: "It reduced cycle time by 30%.",
      }),
    );
    expect(composer).toHaveValue("");
  });

  it("renders streamed text and can stop the active turn", async () => {
    sendMessage.mockResolvedValue({ runId: "run-stream" });
    const user = userEvent.setup();
    render(<CoachPage />);
    await user.type(screen.getByLabelText("Message your Profile Coach"), "Evidence");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() =>
      FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "Strong answer." } }),
    );
    expect(await screen.findByText("Strong answer.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(cancelRun).toHaveBeenCalledWith("run-stream");
    expect(screen.queryByText("Strong answer.")).not.toBeInTheDocument();
  });

  it("stopping the end-session stream suppresses its late completion", async () => {
    let capturedOnDone: ((completed: { runId: string; status: string; error?: string }) => void) | undefined;
    endSession.mockImplementation(async ({ onDone }) => {
      capturedOnDone = onDone;
      return { runId: "run-end" };
    });
    const user = userEvent.setup();
    render(<CoachPage />);

    await user.click(screen.getByRole("button", { name: "End session" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "End session" }));
    expect(endSession).toHaveBeenCalled();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    act(() =>
      FakeEventSource.last!.send({ i: 0, t: "text", v: { text: "Preparing your recap..." } }),
    );

    await user.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(capturedOnDone).toBeDefined();
    act(() => capturedOnDone!({ runId: "run-end", status: "failed", error: "Could not end session" }));

    expect(screen.queryByText("Could not end session")).not.toBeInTheDocument();
  });

  it("renders a completed session read-only after it is selected from history", async () => {
    coachState.status = "ended";
    coachState.recap = "You documented a measurable delivery outcome.";
    coachState.sessions = [{ sessionId: "session-1", status: "ended", startedAt: "2026-07-15T12:00:00Z", endedAt: "2026-07-15T13:00:00Z", topicCount: 1, savedNoteCount: 0, archivedAt: null }];
    const user = userEvent.setup();

    render(<CoachPage />);
    await user.click(screen.getByRole("button", { name: /^Coaching · 7\/15\/2026/i }));

    expect(screen.queryByLabelText("Message your Profile Coach")).not.toBeInTheDocument();
    expect(screen.getByText(coachState.recap)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start another session/i })).toBeInTheDocument();
  });

  it("archives an ended session from its past-session row", async () => {
    coachState.sessions = [
      { sessionId: "session-1", status: "active", startedAt: "2026-07-18T12:00:00Z", endedAt: null, topicCount: 1, savedNoteCount: 0, archivedAt: null },
      { sessionId: "c1", status: "ended", startedAt: "2026-07-15T12:00:00Z", endedAt: "2026-07-15T13:00:00Z", topicCount: 2, savedNoteCount: 1, archivedAt: null },
    ];
    const user = userEvent.setup();
    render(<CoachPage />);
    await user.click(screen.getByRole("button", { name: "Actions for Coaching · 7/15/2026" }));
    await user.click(await screen.findByRole("menuitem", { name: "Archive" }));
    expect(archiveSession).toHaveBeenCalledWith({ sessionId: "c1" }, expect.any(Object));
  });

  it("warns that saved notes survive deletion", async () => {
    coachState.sessions = [
      { sessionId: "session-1", status: "active", startedAt: "2026-07-18T12:00:00Z", endedAt: null, topicCount: 1, savedNoteCount: 0, archivedAt: null },
      { sessionId: "c1", status: "ended", startedAt: "2026-07-15T12:00:00Z", endedAt: "2026-07-15T13:00:00Z", topicCount: 2, savedNoteCount: 1, archivedAt: null },
    ];
    const user = userEvent.setup();
    render(<CoachPage />);
    await user.click(screen.getByRole("button", { name: "Actions for Coaching · 7/15/2026" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByText(/Saved notes are kept in your profile/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteSession).toHaveBeenCalledWith({ sessionId: "c1" }, expect.any(Object));
  });

  it("includes archived sessions when toggled", async () => {
    const user = userEvent.setup();
    render(<CoachPage />);
    await user.click(screen.getByRole("checkbox", { name: "Show archived" }));
    expect(coachState.includeArchived).toBe(true);
  });
});
