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

describe("AttentionCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.records.mockReturnValue({ data: { records: [{ id: 1, kind: "source", sourceLabel: "companies:https://x", message: "HTTP 403", count: 3, firstSeenAt: "2026-07-18T12:00:00Z", lastSeenAt: "2026-07-18T12:00:00Z", status: "open", runId: null }] }, isPending: false, isError: false, refetch: vi.fn() });
  });

  it("renders open errors with dismiss, resolve, and clear all", async () => {
    const user = userEvent.setup();
    render(<AttentionCard />);
    expect(screen.getByText(/seen 3×/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(mocks.dismiss).toHaveBeenCalledWith({ id: 1 });
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    expect(mocks.resolve).toHaveBeenCalledWith({ id: 1 });
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(mocks.clear).toHaveBeenCalled();
  });

  it("shows no open errors when empty", () => {
    mocks.records.mockReturnValue({ data: { records: [] }, isPending: false, isError: false, refetch: vi.fn() });
    render(<AttentionCard />);
    expect(screen.getByText("No open errors.")).toBeInTheDocument();
  });
});
