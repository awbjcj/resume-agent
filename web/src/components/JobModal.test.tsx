import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { JobModal } from "./JobModal";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

const jobPayload = (overrides: Record<string, unknown> = {}) => ({
  id: 42,
  source: "greenhouse",
  url: null,
  company: "Acme",
  title: "Staff Engineer",
  location: "Remote",
  jdText: "Build things.",
  status: "approved",
  fitScore: 80,
  fitRationale: "Strong match.",
  criteriaJson: null,
  postedAt: null,
  archivedAt: null,
  createdAt: "2026-06-01T00:00:00Z",
  hasProgress: false,
  application: null,
  resumeVersions: [],
  skills: [],
  ...overrides,
});

describe("JobModal", () => {
  it("renders job detail with a heading and the JD text", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /staff engineer/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Build things.")).toBeInTheDocument();
  });

  it("shows the rejection reason banner for a rejected job", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            status: "rejected",
            fitRationale: null,
            rejectReason: "off-target role: not a backend posting",
          }),
        ),
      ),
    );
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/rejected during discovery/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText("off-target role: not a backend posting"),
    ).toBeInTheDocument();
  });

  it("shows the hard-filter reason banner for a filtered rejection", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            status: "rejected",
            fitRationale: null,
            rejectReason: "salary below minimum",
            rejectCategory: "filtered",
          }),
        ),
      ),
    );
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/filtered out during discovery/i)).toBeInTheDocument(),
    );
    expect(screen.getByText("salary below minimum")).toBeInTheDocument();
  });

  it("groups skills into must-have / best-have with a coverage tally", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            skills: [
              { name: "Python", covered: true, required: true },
              { name: "Kafka", covered: false, required: true },
              { name: "Rust", covered: false, required: false },
            ],
          }),
        ),
      ),
    );
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("Must-have")).toBeInTheDocument());
    expect(screen.getByText("Nice-to-have")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Rust")).toBeInTheDocument();
    expect(screen.getByText("1/3 covered")).toBeInTheDocument();
  });

  it("renders prev/next buttons and reflects disabled boundaries", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(
      <JobModal
        jobId={42}
        onClose={() => {}}
        onPrev={() => {}}
        onNext={() => {}}
        hasPrev={false}
        hasNext={true}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /previous job/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next job/i })).toBeEnabled();
  });

  it("calls onPrev/onNext when the buttons are clicked", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    const onPrev = vi.fn();
    const onNext = vi.fn();
    wrap(
      <JobModal
        jobId={42}
        onClose={() => {}}
        onPrev={onPrev}
        onNext={onNext}
        hasPrev
        hasNext
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /next job/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /next job/i }));
    fireEvent.click(screen.getByRole("button", { name: /previous job/i }));
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("navigates with arrow keys but ignores them while editing a field", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    const onNext = vi.fn();
    wrap(
      <JobModal jobId={42} onClose={() => {}} onPrev={() => {}} onNext={onNext} hasPrev hasNext />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /next job/i })).toBeInTheDocument(),
    );

    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(onNext).toHaveBeenCalledTimes(1);

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(onNext).toHaveBeenCalledTimes(1); // still 1 — ignored inside an input
    input.remove();
  });

  it("omits the nav buttons when no handlers are provided", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /next job/i })).not.toBeInTheDocument();
  });

  it("uses the wide modal size and a tight version count", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            resumeVersions: [
              { id: 1, createdAt: "2026-06-02T00:00:00Z" },
              { id: 2, createdAt: "2026-06-03T00:00:00Z" },
              { id: 3, createdAt: "2026-06-04T00:00:00Z" },
            ],
          }),
        ),
      ),
    );
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("sm:max-w-7xl");

    const versionsTab = screen.getByRole("tab", { name: /versions/i });
    expect(versionsTab).toHaveTextContent("Versions3");
    const count = versionsTab.querySelector("span");
    expect(count?.className).not.toContain("ml-1.5");
    expect(count?.className).toContain("leading-none");
  });

  it("opens redo for the single job it is showing", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    const user = userEvent.setup();
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );

    await user.click(await screen.findByRole("button", { name: /^redo/i }));

    expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
  });

  it("places H-1B research inside the Management tab", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json(
          jobPayload({
            h1BSponsorship: {
              capability: "unavailable",
              message: "No H-1B evidence has been checked for this job yet.",
              evidence: null,
            },
          }),
        ),
      ),
    );
    const user = userEvent.setup();
    wrap(<JobModal jobId={42} onClose={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("tab", { name: "Management" }));

    expect(
      screen.getByRole("heading", { name: "Historical H-1B sponsorship" }),
    ).toBeInTheDocument();
  });
});
