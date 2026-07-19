import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InterviewPage } from "./InterviewPage";

const mocks = vi.hoisted(() => ({
  sessions: vi.fn(),
  session: vi.fn(),
  send: vi.fn(),
  end: vi.fn(),
  start: vi.fn(),
  archive: vi.fn(),
  unarchive: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("./use-interview", () => ({
  useInterviewSessions: () => mocks.sessions(),
  useInterviewSession: () => mocks.session(),
  useSendInterviewAnswer: () => mocks.send(),
  useEndInterview: () => mocks.end(),
  useStartInterview: () => mocks.start(),
  useArchiveInterviewSession: () => ({ mutate: mocks.archive }),
  useUnarchiveInterviewSession: () => ({ mutate: mocks.unarchive }),
  useDeleteInterviewSession: () => ({ mutate: mocks.remove, isPending: false }),
}));

vi.mock("@/components/TranscribeButton", () => ({ TranscribeButton: () => null }));
vi.mock("./NewInterviewDialog", () => ({
  NewInterviewDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">New mock interview</div> : null,
}));

function activeSession(overrides = {}) {
  return {
    sessionId: "s1",
    jobId: 7,
    resumeVersionId: 3,
    company: "Acme",
    title: "Engineer",
    startedAt: "2026-07-17T00:00:00+00:00",
    endedAt: null,
    status: "active",
    concluded: false,
    style: { stage: "technical", demeanor: "neutral", difficulty: "standard", questionCount: 4, extra: "" },
    progress: { asked: 2, total: 4 },
    plan: null,
    turns: [{ role: "interviewer", text: "Tell me about yourself.", questionId: "q1", isFollowup: false, at: "" }],
    debrief: null,
    ...overrides,
  };
}

function renderPage(entry = "/interview?session=s1") {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(<InterviewPage />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sessions.mockReturnValue({ data: { sessions: [] }, isLoading: false, isError: false });
  mocks.session.mockReturnValue({ data: activeSession(), isLoading: false, isError: false, refetch: vi.fn() });
  mocks.send.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  mocks.end.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  mocks.start.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
});

describe("InterviewPage", () => {
  it("shows company, title, and question progress in the header", () => {
    renderPage();
    expect(screen.getByText(/Acme/)).toBeInTheDocument();
    expect(screen.getByText(/Engineer/)).toBeInTheDocument();
    expect(screen.getByText(/Question 2 of 4/)).toBeInTheDocument();
  });

  it("shows the sessions rail and selects the active session by default", () => {
    mocks.sessions.mockReturnValue({
      data: { sessions: [{ ...activeSession(), askedCount: 2, questionCount: 4, overallScore: null, archivedAt: null }] },
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    });
    renderPage("/interview");
    expect(screen.getByRole("heading", { name: "Sessions" })).toBeInTheDocument();
    expect(screen.getAllByText(/Question 2 of 4/)).toHaveLength(2);
  });

  it("opens the new interview dialog from the rail", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /new interview/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("disables the composer while an answer run is pending", () => {
    mocks.send.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });
    renderPage();
    expect(screen.getByRole("textbox", { name: /answer/i })).toBeDisabled();
  });

  it("shows a debrief call-to-action when the interview is concluded", async () => {
    const endMutate = vi.fn().mockResolvedValue({});
    mocks.end.mockReturnValue({ mutateAsync: endMutate, isPending: false });
    mocks.session.mockReturnValue({
      data: activeSession({ concluded: true }),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    renderPage();
    const cta = screen.getByRole("button", { name: /debrief/i });
    await userEvent.click(cta);
    expect(endMutate).toHaveBeenCalledWith(expect.objectContaining({ sessionId: "s1" }));
  });

  it("renders the debrief and revealed plan for an ended session", () => {
    mocks.session.mockReturnValue({
      data: activeSession({
        status: "ended",
        endedAt: "2026-07-17T01:00:00+00:00",
        plan: [{ id: "q1", competency: "Python", questionType: "role_specific", status: "done" }],
        debrief: {
          summary: "Solid rehearsal.",
          questionReviews: [
            { questionId: "q1", question: "Python background", score: 4, strengths: ["clear"], improvements: ["add numbers"], suggestedAnswer: "..." },
          ],
          strengths: ["communication"],
          improvements: ["quantify"],
          starNotes: "Use STAR.",
        },
      }),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("Solid rehearsal.")).toBeInTheDocument();
    expect(screen.getByText("Python background")).toBeInTheDocument();
    expect(screen.getByText("4/5")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument(); // revealed plan competency
  });

  it("confirms before ending an in-progress interview", async () => {
    const endMutate = vi.fn().mockResolvedValue({});
    mocks.end.mockReturnValue({ mutateAsync: endMutate, isPending: false });
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /end interview/i }));
    expect(endMutate).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /end interview/i }));
    expect(endMutate).toHaveBeenCalledWith(expect.objectContaining({ sessionId: "s1" }));
  });
});
