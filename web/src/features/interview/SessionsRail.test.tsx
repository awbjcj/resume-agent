import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionsRail } from "./SessionsRail";

const mocks = vi.hoisted(() => ({
  sessions: vi.fn(),
  archive: vi.fn(),
  unarchive: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("./use-interview", () => ({
  useInterviewSessions: (...args: unknown[]) => mocks.sessions(...args),
  useArchiveInterviewSession: () => ({ mutate: mocks.archive }),
  useUnarchiveInterviewSession: () => ({ mutate: mocks.unarchive }),
  useDeleteInterviewSession: () => ({ mutate: mocks.remove, isPending: false }),
}));
vi.mock("./NewInterviewDialog", () => ({
  NewInterviewDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">New mock interview</div> : null,
}));

const sessions = [
  {
    sessionId: "s1",
    jobId: 1,
    company: "Acme",
    title: "Engineer",
    status: "active",
    startedAt: "2026-07-18T00:00:00Z",
    endedAt: null,
    askedCount: 2,
    questionCount: 4,
    overallScore: null,
    archivedAt: null,
  },
  {
    sessionId: "s2",
    jobId: 2,
    company: "Beta",
    title: "Lead",
    status: "ended",
    startedAt: "2026-07-17T00:00:00Z",
    endedAt: "2026-07-17T01:00:00Z",
    askedCount: 4,
    questionCount: 4,
    overallScore: 4.2,
    archivedAt: null,
  },
];

describe("SessionsRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.sessions.mockReturnValue({
      data: { sessions },
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    });
  });

  it("groups sessions into in-progress and completed", () => {
    render(<MemoryRouter><SessionsRail selectedId={null} /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "In progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Completed" })).toBeInTheDocument();
    expect(screen.getByText("Acme · Engineer")).toBeInTheDocument();
    expect(screen.getByText("Beta · Lead")).toBeInTheDocument();
  });

  it("warns before deleting an active session", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><SessionsRail selectedId={null} /></MemoryRouter>);

    await user.click(screen.getByRole("button", { name: "Actions for Acme · Engineer" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByText(/without a debrief/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(mocks.remove).toHaveBeenCalledWith(
      { sessionId: "s1" },
      expect.any(Object),
    );
  });

  it("refetches with archived sessions when toggled", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><SessionsRail selectedId={null} /></MemoryRouter>);

    await user.click(screen.getByRole("switch", { name: "Show archived" }));
    expect(mocks.sessions).toHaveBeenLastCalledWith(undefined, true);
  });
});
