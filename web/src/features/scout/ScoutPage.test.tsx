import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { withQueryClient } from "@/test/utils";

const mocks = vi.hoisted(() => ({ start: vi.fn(), send: vi.fn(), end: vi.fn(), session: null as Record<string, unknown> | null }));
vi.mock("./use-scout", async (original) => ({
  ...(await original()),
  useScoutSessions: () => ({ data: { sessions: [] }, isLoading: false, isError: false, refetch: vi.fn() }),
  useScoutSession: () => ({ data: mocks.session, isLoading: false, isError: false, refetch: vi.fn() }),
  useStartScoutSession: () => ({ mutateAsync: mocks.start, isPending: false }),
  useSendScoutMessage: () => ({ mutateAsync: mocks.send, isPending: false }),
  useEndScoutSession: () => ({ mutateAsync: mocks.end, isPending: false }),
  useArchiveScoutSession: () => ({ mutate: vi.fn() }), useUnarchiveScoutSession: () => ({ mutate: vi.fn() }), useDeleteScoutSession: () => ({ mutate: vi.fn() }),
  useApproveScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/chat/useChatStream", () => ({ useChatStream: () => ({ parts: [], status: "idle", error: null, stop: vi.fn(), reset: vi.fn() }) }));
vi.mock("@/lib/runs/store", () => ({ useRunStore: () => null }));
import { ScoutPage } from "./ScoutPage";

beforeEach(() => { vi.clearAllMocks(); mocks.session = null; mocks.start.mockResolvedValue({ runId: "r1" }); });

it("starts discovery from a concrete empty-state composer", async () => {
  render(<ScoutPage />, { wrapper: withQueryClient });
  const input = screen.getByLabelText("Discovery request");
  await userEvent.type(input, "Find healthcare platform roles");
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(mocks.start).toHaveBeenCalledWith(expect.objectContaining({ message: "Find healthcare platform roles" }));
  expect(screen.getByText("Proposal ledger")).toBeInTheDocument();
});

it("keeps pending proposals actionable after a session ends", () => {
  mocks.session = { sessionId: "s1", goal: "Climate", status: "ended", startedAt: "now", endedAt: "now", archivedAt: null, recap: "Three good leads", scrapeAvailable: true, scrapeUnavailableReason: null, turns: [], proposals: [{ id: "p1", kind: "source", status: "pending", check: "validated", reason: "Fit", fitScore: 90, checkError: "", dismissReason: "", resolvedAt: null, citations: [], source: { company: "Acme", url: "https://acme.test", ats: "greenhouse", roleCount: 2, token: "acme", errorCode: null }, term: null }] };
  render(<ScoutPage />, { wrapper: withQueryClient });
  expect(screen.queryByLabelText("Discovery request")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Acme" })).toBeEnabled();
  expect(screen.getByText("Three good leads")).toBeInTheDocument();
});
