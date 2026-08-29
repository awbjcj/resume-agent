import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { openDownload } from "@/lib/api/client";
import { UpcomingCard } from "./UpcomingCard";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, openDownload: vi.fn().mockResolvedValue(undefined) };
});

const events = [
  {
    eventId: 42,
    jobId: 7,
    kind: "technical_round",
    sequence: 2,
    customLabel: null,
    occurredAt: "2026-09-01T18:30:00Z",
    allDay: false,
    timezone: "America/New_York",
    modality: "video",
    platform: "zoom",
    locationOrLink: "https://zoom.example/interview",
    company: "Acme",
    title: "Staff Engineer",
  },
];

describe("UpcomingCard", () => {
  it("shows a compact event summary with job and calendar actions", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UpcomingCard events={events} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Next 7 days" })).toBeInTheDocument();
    expect(screen.getByText("Technical round 2")).toBeInTheDocument();
    expect(screen.getByText(/Acme · Staff Engineer/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view acme/i })).toHaveAttribute(
      "href",
      "/pipeline?job=7",
    );

    await user.click(screen.getByRole("button", { name: /download upcoming calendar/i }));
    expect(openDownload).toHaveBeenCalledWith("/api/applications/upcoming.ics");
  });

  it("stays absent when there is nothing scheduled", () => {
    const { container } = render(<UpcomingCard events={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
