import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttentionCard } from "./AttentionCard";

const mocks = vi.hoisted(() => ({ records: vi.fn(), dismiss: vi.fn(), resolve: vi.fn(), clear: vi.fn() }));
vi.mock("@/features/errors/use-errors", () => ({
  useErrorRecords: () => mocks.records(),
  useDismissError: () => ({ mutate: mocks.dismiss, isPending: false }),
  useResolveError: () => ({ mutate: mocks.resolve, isPending: false }),
  useDismissAllErrors: () => ({ mutate: mocks.clear, isPending: false }),
}));

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function renderAttentionCard(records: Record<string, unknown>[]) {
  mocks.records.mockReturnValue({
    data: { records, pagination: { page: 1, pageSize: 50, totalItems: records.length, totalPages: 1 } },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  });
  return wrap(<AttentionCard />);
}

describe("AttentionCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders open errors with dismiss, resolve, and clear all", async () => {
    const user = userEvent.setup();
    renderAttentionCard([
      {
        id: 1, kind: "source", sourceLabel: "companies:https://x", message: "HTTP 403",
        count: 3, firstSeenAt: "2026-07-18T12:00:00Z", lastSeenAt: "2026-07-18T12:00:00Z",
        status: "open", runId: null, jobDetails: null,
      },
    ]);
    expect(screen.getByText(/seen 3×/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(mocks.dismiss).toHaveBeenCalledWith({ id: 1 });
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    expect(mocks.resolve).toHaveBeenCalledWith({ id: 1 });
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(mocks.clear).toHaveBeenCalled();
  });

  it("shows no open errors when empty", () => {
    renderAttentionCard([]);
    expect(screen.getByText("No open errors.")).toBeInTheDocument();
  });

  const jobRecord = {
    id: 1,
    kind: "job",
    sourceLabel: "job:42:tailor",
    message: "ValueError: match_plan_enabled requires a match-plan agent",
    status: "open",
    count: 3,
    runId: null,
    firstSeenAt: new Date().toISOString(),
    lastSeenAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    jobDetails: {
      jobId: 42,
      stage: "tailor",
      errorType: "ValueError",
      message: "match_plan_enabled requires a match-plan agent",
      company: "Acme",
      title: "Staff Engineer",
      model: "openai:gpt-5",
      tracebackTail: "Traceback (most recent call last): ...",
    },
  };

  const sourceRecord = {
    ...jobRecord,
    id: 2,
    kind: "source",
    sourceLabel: "workday:acme",
    message: "HTTP 500",
    count: 1,
    jobDetails: null,
  };

  it("groups failures by kind", async () => {
    renderAttentionCard([jobRecord, sourceRecord]);

    expect(await screen.findByRole("heading", { name: /jobs/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /sources/i })).toBeInTheDocument();
  });

  it("formats a job failure instead of showing the raw label", async () => {
    renderAttentionCard([jobRecord]);

    expect(await screen.findByText(/Acme — Staff Engineer/)).toBeInTheDocument();
    expect(screen.getByText("tailor")).toBeInTheDocument();
    expect(screen.getByText(/openai:gpt-5/)).toBeInTheDocument();
    expect(screen.getByText(/×3/)).toBeInTheDocument();
    expect(screen.queryByText("job:42:tailor")).toBeNull();
  });

  it("hides the traceback until the expander is opened", async () => {
    const user = userEvent.setup();
    renderAttentionCard([jobRecord]);

    expect(screen.queryByText(/Traceback \(most recent call last\)/)).toBeNull();
    await user.click(await screen.findByRole("button", { name: /technical details/i }));

    expect(screen.getByText(/Traceback \(most recent call last\)/)).toBeInTheDocument();
  });

  it("opens redo for that job and stage when Retry is clicked", async () => {
    const user = userEvent.setup();
    renderAttentionCard([jobRecord]);

    await user.click(await screen.findByRole("button", { name: /retry/i }));

    expect(
      await screen.findByRole("checkbox", { name: /re-tailor resume/i }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /re-pull job description/i }),
    ).not.toBeChecked();
    expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
  });

  it("shows only the first 8 rows until expanded", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 12 }, (_, index) => ({
      ...jobRecord,
      id: index + 1,
      jobDetails: { ...jobRecord.jobDetails, jobId: index + 1 },
    }));
    renderAttentionCard(many);

    expect(await screen.findAllByRole("button", { name: /retry/i })).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: /show all 12/i }));

    expect(screen.getAllByRole("button", { name: /retry/i })).toHaveLength(12);
  });
});
