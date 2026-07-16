import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoachPage } from "./CoachPage";

const sendMessage = vi.fn();
const saveNote = vi.fn();
const discardNote = vi.fn();
const coachState = vi.hoisted(() => ({ status: "active", recap: null as string | null }));

vi.mock("./use-coach", () => ({
  useCoachSessions: () => ({
    data: {
      sessions: [
        {
          sessionId: "session-1",
          status: coachState.status,
          startedAt: "2026-07-15T12:00:00Z",
          endedAt: null,
          topicCount: 1,
          savedNoteCount: 0,
        },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useCoachSession: () => ({
    data: {
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
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useStartCoachSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSendCoachMessage: () => ({ mutateAsync: sendMessage, isPending: false }),
  useEndCoachSession: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCoachNote: () => ({ mutateAsync: saveNote, isPending: false }),
  useDiscardCoachNote: () => ({ mutateAsync: discardNote, isPending: false }),
}));

describe("CoachPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    coachState.status = "active";
    coachState.recap = null;
    sendMessage.mockImplementation(async ({ onDone }) => {
      onDone?.({ status: "succeeded" });
      return { runId: "run-1" };
    });
  });

  it("renders the active coaching thread and agenda", () => {
    render(<CoachPage />);

    expect(screen.getByRole("heading", { name: "Profile coach" })).toBeInTheDocument();
    expect(screen.getByText("What changed after you shipped it?")).toBeInTheDocument();
    expect(screen.getByText("Missing outcome")).toBeInTheDocument();
    expect(screen.getByText("Improved delivery")).toBeInTheDocument();
  });

  it("preserves a message until its run succeeds", async () => {
    const user = userEvent.setup();
    render(<CoachPage />);

    const composer = screen.getByLabelText("Message your profile coach");
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

  it("renders a completed session read-only", () => {
    coachState.status = "ended";
    coachState.recap = "You documented a measurable delivery outcome.";

    render(<CoachPage />);

    expect(screen.queryByLabelText("Message your profile coach")).not.toBeInTheDocument();
    expect(screen.getByText(coachState.recap)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start another session/i })).toBeInTheDocument();
  });
});
