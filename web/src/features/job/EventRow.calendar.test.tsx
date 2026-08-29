import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { openDownload } from "@/lib/api/client";
import { withQueryClient } from "@/test/utils";
import { EventRow } from "./EventRow";
import type { ApplicationEvent } from "./use-application-events";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, openDownload: vi.fn().mockResolvedValue(undefined) };
});

describe("EventRow calendar action", () => {
  it("downloads a purpose-bound calendar file for a dated event", async () => {
    const user = userEvent.setup();
    const event = {
      id: 13,
      applicationId: 5,
      kind: "technical_phone_screen",
      sequence: 1,
      customLabel: null,
      occurredAt: "2027-03-09T19:00:00Z",
      allDay: false,
      timezone: "America/New_York",
      modality: "phone",
      locationOrLink: null,
      platform: null,
      platformOther: null,
      durationMinutes: 30,
      interviewers: null,
      result: "scheduled",
      notes: null,
      reflection: null,
      compBase: null,
      compBonus: null,
      compEquityAnnual: null,
      compSigning: null,
      compCurrency: null,
      totalComp: null,
      source: "manual",
      createdAt: "2026-08-29T00:00:00Z",
      updatedAt: "2026-08-29T00:00:00Z",
    } satisfies ApplicationEvent;

    render(<EventRow event={event} jobId={7} />, { wrapper: withQueryClient });
    await user.click(
      screen.getByRole("button", { name: /add technical phone screen to calendar/i }),
    );

    expect(openDownload).toHaveBeenCalledWith("/api/jobs/7/events/13.ics");
  });
});
