import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { withQueryClient } from "@/test/utils";

const mocks = vi.hoisted(() => ({ start: vi.fn(), send: vi.fn(), end: vi.fn(), remove: vi.fn(), session: null as Record<string, unknown> | null, sessions: [] as Record<string, unknown>[], includeArchived: false }));
vi.mock("./use-scout", async (original) => ({
  ...(await original()),
  useScoutSessions: (includeArchived = false) => { mocks.includeArchived = includeArchived; return { data: { sessions: mocks.sessions }, isLoading: false, isError: false, refetch: vi.fn() }; },
  useScoutSession: () => ({ data: mocks.session, isLoading: false, isError: false, refetch: vi.fn() }),
  useStartScoutSession: () => ({ mutateAsync: mocks.start, isPending: false }),
  useSendScoutMessage: () => ({ mutateAsync: mocks.send, isPending: false }),
  useEndScoutSession: () => ({ mutateAsync: mocks.end, isPending: false }),
  useArchiveScoutSession: () => ({ mutate: vi.fn() }), useUnarchiveScoutSession: () => ({ mutate: vi.fn() }), useDeleteScoutSession: () => ({ mutate: mocks.remove, isPending: false }),
  useApproveScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }), useDismissScoutProposal: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/chat/useChatStream", () => ({ useChatStream: () => ({ parts: [], status: "idle", error: null, stop: vi.fn(), reset: vi.fn() }) }));
vi.mock("@/lib/runs/store", () => ({ useRunStore: () => null }));
import { ScoutPage } from "./ScoutPage";

beforeEach(() => { vi.clearAllMocks(); mocks.session = null; mocks.sessions = []; mocks.includeArchived = false; mocks.start.mockResolvedValue({ runId: "r1" }); });

it("starts discovery from a concrete empty-state composer", async () => {
  render(<ScoutPage />, { wrapper: withQueryClient });
  const input = screen.getByLabelText("Discovery request");
  await userEvent.type(input, "Find healthcare platform roles");
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(mocks.start).toHaveBeenCalledWith(expect.objectContaining({ message: "Find healthcare platform roles" }));
  expect(screen.getByText("Review proposals")).toBeInTheDocument();
});

it("echoes the sent message into the thread before the turn finishes", async () => {
  mocks.session = { sessionId: "s1", goal: "Climate", status: "active", startedAt: "now", endedAt: null, archivedAt: null, recap: null, scrapeAvailable: true, scrapeUnavailableReason: null, proposals: [], turns: [{ role: "user", kind: "", text: "Find climate roles", at: "t0", notice: "", proposalIds: [] }, { role: "scout", kind: "reply", text: "Here are some leads.", at: "t1", notice: "", proposalIds: [] }] };
  mocks.send.mockResolvedValue({ runId: "r2" });
  render(<ScoutPage />, { wrapper: withQueryClient });
  await userEvent.type(screen.getByLabelText("Discovery request"), "Smaller teams please");
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ message: "Smaller teams please" }));
  // Scoped to the thread: the composer is a controlled <textarea>, and jsdom
  // exposes its value as text content, so an unscoped query passes on the
  // input the user just typed into and never sees the missing echo.
  const thread = within(screen.getByTestId("chat-viewport"));
  expect(thread.getByText("Smaller teams please")).toBeInTheDocument();
  expect(thread.getByText("Here are some leads.")).toBeInTheDocument();
});

it("keeps pending proposals actionable after a session ends", () => {
  mocks.session = { sessionId: "s1", goal: "Climate", status: "ended", startedAt: "now", endedAt: "now", archivedAt: null, recap: "Three good leads", scrapeAvailable: true, scrapeUnavailableReason: null, turns: [], proposals: [{ id: "p1", kind: "source", status: "pending", check: "validated", reason: "Fit", fitScore: 90, checkError: "", dismissReason: "", resolvedAt: null, citations: [], source: { company: "Acme", url: "https://acme.test", ats: "greenhouse", roleCount: 2, token: "acme", errorCode: null }, term: null }] };
  render(<ScoutPage />, { wrapper: withQueryClient });
  expect(screen.queryByLabelText("Discovery request")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Acme" })).toBeEnabled();
  expect(screen.getByText("Three good leads")).toBeInTheDocument();
});

it("groups archived filtering with history and confirms deletion in-app", async () => {
  const user = userEvent.setup();
  mocks.sessions = [{ sessionId: "old", goal: "Older search", status: "ended", startedAt: "now", endedAt: "now", archivedAt: null, proposalCount: 3, addedCount: 1 }];
  render(<ScoutPage />, { wrapper: withQueryClient });

  await user.click(screen.getByRole("checkbox", { name: "Show archived" }));
  expect(mocks.includeArchived).toBe(true);
  await user.click(screen.getByRole("button", { name: "Delete Older search" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/permanently removed/i)).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(mocks.remove).toHaveBeenCalledWith({ sessionId: "old" });
});
