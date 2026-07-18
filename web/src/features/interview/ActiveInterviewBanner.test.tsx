import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveInterviewBanner } from "./ActiveInterviewBanner";

const mocks = vi.hoisted(() => ({ sessions: vi.fn(), end: vi.fn() }));

vi.mock("./use-interview", () => ({
  useInterviewSessions: () => mocks.sessions(),
  useEndInterview: () => mocks.end(),
}));

const activeSession = {
  sessionId: "s9",
  jobId: 7,
  company: "Acme",
  title: "Engineer",
  startedAt: "2026-07-18T00:00:00Z",
  endedAt: null,
  status: "active",
  askedCount: 1,
  questionCount: 4,
  overallScore: null,
};

function renderAt(path: string, sessions: unknown[]) {
  mocks.sessions.mockReturnValue({ data: { sessions } });
  mocks.end.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ActiveInterviewBanner />
    </MemoryRouter>,
  );
}

describe("ActiveInterviewBanner", () => {
  beforeEach(() => vi.clearAllMocks());

  it("surfaces a resumable active interview from any page", () => {
    renderAt("/dashboard", [activeSession]);
    expect(screen.getByText(/Mock interview in progress/i)).toBeInTheDocument();
    expect(screen.getByText(/Acme · Engineer/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /resume/i })).toHaveAttribute(
      "href",
      "/interview?session=s9",
    );
    expect(screen.getByRole("button", { name: /^end$/i })).toBeInTheDocument();
  });

  it("renders nothing when no session is active", () => {
    const { container } = renderAt("/dashboard", [{ ...activeSession, status: "ended" }]);
    expect(container).toBeEmptyDOMElement();
  });

  it("stays hidden on the interview page itself", () => {
    const { container } = renderAt("/interview", [activeSession]);
    expect(container).toBeEmptyDOMElement();
  });
});
