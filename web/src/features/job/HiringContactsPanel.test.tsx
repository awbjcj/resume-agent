import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { HiringContactsPanel } from "./HiringContactsPanel";

const mocks = vi.hoisted(() => ({ trackRun: vi.fn(), writeText: vi.fn() }));
vi.mock("@/lib/runs/tracker", () => ({ trackRun: mocks.trackRun }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const ready = {
  state: "ready",
  reason: null,
  canRefresh: true,
  intelligence: {
    jobId: 42,
    company: "Acme",
    title: "Platform Engineer",
    retrievedAt: "2026-08-30T12:00:00Z",
    contacts: [
      {
        name: "Avery Chen",
        publicRole: "VP of Platform",
        contactType: "team_leader",
        sourceUrls: ["https://acme.example/team/avery"],
        verificationState: "single_source",
        whyRelevant: "Publicly leads the platform organization.",
        emailDraft: "Hello Avery",
        shortMessageDraft: "Hello Avery — may I ask about the team?",
      },
    ],
    genericEmailDraft: "Hello recruiting team",
    genericShortMessageDraft: "Hello team",
    caveat: "This feature never sends a message.",
  },
};

describe("HiringContactsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("renders public grounding, copy-only drafts, and the permanent no-send notice", async () => {
    server.use(
      http.get("/api/jobs/42/hiring-contact-intelligence", () =>
        HttpResponse.json(ready),
      ),
    );
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: mocks.writeText.mockResolvedValue(undefined) },
    });
    const { container } = render(<HiringContactsPanel jobId={42} />, { wrapper });

    expect(await screen.findByText("Avery Chen")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /public source/i })).toHaveAttribute(
      "href",
      "https://acme.example/team/avery",
    );
    expect(screen.getByText(/never sends messages/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy email draft" }));
    expect(mocks.writeText).toHaveBeenCalledWith("Hello Avery");
    expect((await axe(container)).violations).toEqual([]);
  });

  it("launches an explicit contact research run", async () => {
    server.use(
      http.get("/api/jobs/42/hiring-contact-intelligence", () =>
        HttpResponse.json({
          state: "empty",
          reason: "not_generated",
          canRefresh: true,
          intelligence: null,
          message: "Search public sources.",
        }),
      ),
      http.post("/api/jobs/42/hiring-contact-intelligence/refreshes", () =>
        HttpResponse.json(
          { runId: "run-contact", kind: "hiringContactIntelligence", meta: { jobId: 42 } },
          { status: 202 },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<HiringContactsPanel jobId={42} />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Research contacts" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Researching…" })).toBeDisabled(),
    );
    expect(mocks.trackRun).toHaveBeenCalledWith({
      runId: "run-contact",
      kind: "hiringContactIntelligence",
    });
  });
});
