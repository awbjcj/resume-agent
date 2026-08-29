import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { NotificationsBell } from "./NotificationsBell";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/features/job/EmailDraftDialog", () => ({
  EmailDraftDialog: () => null,
}));

describe("NotificationsBell", () => {
  it("renders follow-up reminders with a draft action", async () => {
    server.use(
      http.get("*/api/notifications", () =>
        HttpResponse.json([
          {
            id: 1,
            applicationId: 1,
            kind: "follow_up",
            proposedStatus: "",
            evidence: "No activity for 20 days — Acme · Eng",
            messageId: "followup:1:2026-06-28",
            state: "pending",
            createdAt: "2026-07-18T00:00:00Z",
            jobId: 7,
            company: "Acme",
            title: "Eng",
          },
        ]),
      ),
    );
    const user = userEvent.setup();
    render(<NotificationsBell />, { wrapper: withQueryClient });

    await user.click(screen.getByRole("button", { name: /notifications/i }));
    expect(await screen.findByText(/follow up: acme/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /draft follow-up/i }),
    ).toBeInTheDocument();
  });

  it("presents event nudges as navigation, never as accept actions", async () => {
    let accepted = false;
    server.use(
      http.get("*/api/notifications", () =>
        HttpResponse.json([
          {
            id: 8,
            applicationId: 3,
            kind: "interview_soon",
            proposedStatus: "",
            evidence: "Tomorrow at 2:00 PM — Acme · Staff Engineer",
            messageId: "event:22:2026-09-01T18:00:00Z",
            state: "pending",
            createdAt: "2026-08-31T18:00:00Z",
            jobId: 7,
            company: "Acme",
            title: "Staff Engineer",
          },
        ]),
      ),
      http.post("*/api/notifications/:id/accept", () => {
        accepted = true;
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <NotificationsBell />
      </MemoryRouter>,
      { wrapper: withQueryClient },
    );

    await user.click(screen.getByRole("button", { name: /notifications/i }));
    expect(await screen.findByText("Interview soon: Acme")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view job/i })).toHaveAttribute(
      "href",
      "/pipeline?job=7",
    );
    expect(accepted).toBe(false);
  });
});
