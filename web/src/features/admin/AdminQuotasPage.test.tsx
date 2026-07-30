import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { AdminQuotasPage } from "./AdminQuotasPage";

const page = (data: unknown[]) => ({
  data,
  pagination: { page: 1, pageSize: 100, totalItems: data.length, totalPages: 1 },
});

function handlers() {
  return [
    http.get("/api/auth/me", () => HttpResponse.json({ username: "owner", role: "admin", authRequired: true, needsEmail: false, emailVerified: true, googleLinked: false })),
    http.get("/api/admin/quota-summary", () => HttpResponse.json({ monthlySpendMicros: 125000000, monthlyCapMicros: 500000000, remainingMicros: 375000000, unpricedCallCount: 2, nextResetAt: "2026-08-01T00:00:00Z" })),
    http.get("/api/admin/quota-tiers", () => HttpResponse.json(page([{ id: "FREE", name: "Free", cycleUnit: "WEEK", cycleCount: 1, allowanceMicros: 1000000, isDefault: true, archivedAt: null, memberCount: 1, spendMicros: 250000 }]))),
    http.get("/api/admin/quota-accounts", () => HttpResponse.json(page([{ userId: "alice0000000", username: "alice", disabled: false, tierId: "FREE", allowanceMicros: 1000000, overrideMicros: null, spentMicros: 250000, recurringRemainingMicros: 750000, creditBalanceMicros: 50000, remainingMicros: 800000, overageMicros: 0, periodStart: "2026-07-30T00:00:00Z", periodEnd: "2026-08-06T00:00:00Z", status: "ACTIVE", sharedCostMicros: 250000, byokCostMicros: 40000, totalTokens: 12345 }]))),
    http.get("/api/admin/quota-accounts/:userId/ledger", () => HttpResponse.json(page([]))),
    http.get("/api/admin/llm-rates", () => HttpResponse.json(page([]))),
    http.get("/api/admin/quota-operations", () => HttpResponse.json(page([]))),
    http.post("/api/admin/quota-operation-previews", () => HttpResponse.json({ id: "preview-1", targetType: "USER", targetValue: "alice0000000", actionType: "GRANT_CREDIT", amountMicros: 1000000, affectedCount: 1, totalEffectMicros: 1000000, expiresAt: "2026-07-30T12:15:00Z" }, { status: 201 })),
  ];
}

function renderPage() {
  server.use(...handlers());
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><AdminQuotasPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminQuotasPage", () => {
  it("filters members, opens the keyboard-accessible drawer, and previews a grant", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Cost quotas" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "alice" })).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Search members" }), "missing");
    expect(screen.queryByRole("cell", { name: "alice" })).not.toBeInTheDocument();
    await user.clear(screen.getByRole("textbox", { name: "Search members" }));
    await user.click(await screen.findByRole("cell", { name: "alice" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("persistent allowance override");
    await user.click(screen.getByRole("button", { name: "Close" }));

    await user.selectOptions(screen.getByRole("combobox", { name: "Target user" }), "alice0000000");
    await user.type(screen.getByPlaceholderText("10.00"), "1.00");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(screen.getByText("1 accounts frozen")).toBeInTheDocument());
    expect(screen.getByText(/Total effect \$1.00/)).toBeInTheDocument();
  });
});
