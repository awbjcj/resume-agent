import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { NotificationsBell } from "./NotificationsBell";

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
});
