import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InterviewTab } from "./InterviewTab";

const mocks = vi.hoisted(() => ({ sessions: vi.fn() }));

vi.mock("./use-interview", () => ({
  useInterviewSessions: () => mocks.sessions(),
}));

vi.mock("./InterviewSetupDialog", () => ({
  InterviewSetupDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="setup-dialog" /> : null,
}));

const version = {
  id: 3,
  createdAt: "2026-07-17T00:00:00Z",
  origin: "tailor",
  reviewScore: 90,
} as never;

function renderTab(props: { versions?: unknown[]; hasJd?: boolean } = {}) {
  mocks.sessions.mockReturnValue({ data: { sessions: [] } });
  return render(
    <MemoryRouter>
      <InterviewTab
        jobId={7}
        versions={(props.versions ?? [version]) as never}
        hasJd={props.hasJd ?? true}
      />
    </MemoryRouter>,
  );
}

describe("InterviewTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("disables start with a hint when no resume versions exist", () => {
    renderTab({ versions: [] });
    expect(screen.getByRole("button", { name: /start mock interview/i })).toBeDisabled();
    expect(screen.getByText(/tailor a resume first/i)).toBeInTheDocument();
  });

  it("disables start when the job has no JD", () => {
    renderTab({ hasJd: false });
    expect(screen.getByRole("button", { name: /start mock interview/i })).toBeDisabled();
  });

  it("opens the setup dialog when enabled", async () => {
    renderTab();
    await userEvent.click(screen.getByRole("button", { name: /start mock interview/i }));
    expect(screen.getByTestId("setup-dialog")).toBeInTheDocument();
  });

  it("lists past sessions with score and links ended ones", () => {
    mocks.sessions.mockReturnValue({
      data: {
        sessions: [
          {
            sessionId: "s1",
            jobId: 7,
            company: "Acme",
            title: "Engineer",
            startedAt: "2026-07-17T00:00:00Z",
            endedAt: "2026-07-17T01:00:00Z",
            status: "ended",
            askedCount: 4,
            questionCount: 4,
            overallScore: 3.5,
          },
        ],
      },
    });
    render(
      <MemoryRouter>
        <InterviewTab jobId={7} versions={[version] as never} hasJd />
      </MemoryRouter>,
    );
    expect(screen.getByText("3.5/5")).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/interview?session=s1");
  });

  it("links an in-progress session so it can be resumed", () => {
    mocks.sessions.mockReturnValue({
      data: {
        sessions: [
          {
            sessionId: "s2",
            jobId: 7,
            company: "Acme",
            title: "Engineer",
            startedAt: "2026-07-18T00:00:00Z",
            endedAt: null,
            status: "active",
            askedCount: 2,
            questionCount: 4,
            overallScore: null,
          },
        ],
      },
    });
    render(
      <MemoryRouter>
        <InterviewTab jobId={7} versions={[version] as never} hasJd />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/interview?session=s2");
    expect(screen.getByText("Resume")).toBeInTheDocument();
    expect(screen.getByText(/In progress/i)).toBeInTheDocument();
  });
});
