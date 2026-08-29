import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ events: [] as unknown[], isPending: false }));

vi.mock("./use-application-events", () => ({
  useApplicationEvents: () => ({ data: mocks.events, isPending: mocks.isPending }),
  useCreateEvent: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateEvent: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteEvent: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ApplicationTimeline } from "./ApplicationTimeline";

const event = (over: Record<string, unknown> = {}) => ({
  id: 1,
  applicationId: 7,
  kind: "technical_round",
  sequence: 2,
  occurredAt: "2026-03-09T19:00:00Z",
  allDay: false,
  result: "pending",
  source: "manual",
  platform: "zoom",
  modality: "virtual",
  createdAt: "2026-03-01T00:00:00Z",
  updatedAt: "2026-03-01T00:00:00Z",
  totalComp: null,
  ...over,
});

describe("ApplicationTimeline", () => {
  it("shows an empty state with an add action", () => {
    mocks.events = [];
    render(<ApplicationTimeline jobId={42} />);
    expect(screen.getByText(/no events yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add event/i })).toBeInTheDocument();
  });

  it("renders round, platform, custom, and compensation details", () => {
    mocks.events = [
      event(),
      event({ id: 2, kind: "custom", customLabel: "Referral ping", occurredAt: null }),
      event({ id: 3, kind: "offer_received", sequence: 1, totalComp: 292000, compCurrency: "USD" }),
    ];
    render(<ApplicationTimeline jobId={42} />);
    expect(screen.getByText("Technical round 2")).toBeInTheDocument();
    expect(screen.getAllByText(/Zoom/).length).toBeGreaterThan(0);
    expect(screen.getByText("Referral ping")).toBeInTheDocument();
    expect(screen.getByText(/292,000/)).toBeInTheDocument();
  });

  it("marks a future event as upcoming", () => {
    mocks.events = [event({ occurredAt: new Date(Date.now() + 86_400_000).toISOString() })];
    render(<ApplicationTimeline jobId={42} />);
    expect(screen.getByText("Upcoming")).toBeInTheDocument();
  });
});
