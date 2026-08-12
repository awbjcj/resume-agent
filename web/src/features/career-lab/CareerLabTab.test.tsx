import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CareerLabTab } from "./CareerLabTab";

const mocks = vi.hoisted(() => ({ sessions: vi.fn() }));

vi.mock("./use-career-lab", () => ({
  useCareerLabSessions: (...args: unknown[]) => mocks.sessions(...args),
}));

vi.mock("./CareerLabSetupDialog", () => ({
  CareerLabSetupDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="setup-dialog" /> : null,
}));

const version = { id: 3, round: 1, origin: "tailor" } as never;

function renderTab() {
  return render(
    <MemoryRouter>
      <CareerLabTab jobId={7} jobLabel="Engineer at Acme" versions={[version]} />
    </MemoryRouter>,
  );
}

function session(overrides: Record<string, unknown> = {}) {
  return {
    sessionId: "s1",
    title: "Negotiation prep",
    goal: "Prepare negotiation points",
    startedAt: "2026-08-11T00:00:00Z",
    endedAt: null,
    status: "active",
    archivedAt: null,
    jobId: 7,
    turnCount: 4,
    ...overrides,
  };
}

describe("CareerLabTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.sessions.mockReturnValue({ data: { sessions: [] } });
  });

  it("scopes the session query to this job", () => {
    renderTab();
    expect(mocks.sessions).toHaveBeenCalledWith({ jobId: 7 });
  });

  it("renders threads in the order the endpoint returned them", () => {
    // The endpoint orders open-first then newest, so the tab must not re-sort:
    // that is what makes the open thread reachable on page 1 at any count.
    mocks.sessions.mockReturnValue({
      data: {
        sessions: [
          session({ sessionId: "open-old", title: "Open thread", startedAt: "2026-08-01T00:00:00Z" }),
          session({
            sessionId: "ended-new",
            title: "Ended thread",
            status: "ended",
            startedAt: "2026-08-09T00:00:00Z",
          }),
        ],
      },
    });
    renderTab();

    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      expect.stringContaining("Open thread"),
      expect.stringContaining("Ended thread"),
    ]);
  });

  it("opens the setup dialog from the empty state", async () => {
    renderTab();
    expect(screen.queryByTestId("setup-dialog")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: /start a career lab thread/i }),
    );
    expect(screen.getByTestId("setup-dialog")).toBeInTheDocument();
  });

  it("links an open thread and withdraws the start button", () => {
    mocks.sessions.mockReturnValue({ data: { sessions: [session()] } });
    renderTab();

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/career-lab?session=s1",
    );
    expect(screen.getByText("Continue")).toBeInTheDocument();
    expect(screen.getByText(/thread for this job is open/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /start a career lab thread/i }),
    ).toBeNull();
  });

  it("keeps starting available once every thread has ended", () => {
    mocks.sessions.mockReturnValue({
      data: {
        sessions: [
          session({
            sessionId: "s2",
            status: "ended",
            endedAt: "2026-08-11T01:00:00Z",
            turnCount: 1,
          }),
        ],
      },
    });
    renderTab();

    expect(screen.getByText(/1 turn\b/)).toBeInTheDocument();
    expect(screen.queryByText("Continue")).toBeNull();
    expect(
      screen.getByRole("button", { name: /start a career lab thread/i }),
    ).toBeEnabled();
  });

  it("falls back to the goal when a thread has no title", () => {
    mocks.sessions.mockReturnValue({
      data: { sessions: [session({ title: "" })] },
    });
    renderTab();
    expect(screen.getByText("Prepare negotiation points")).toBeInTheDocument();
  });
});
