import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { AdminQuotasPage } from "./AdminQuotasPage";

const page = (data: unknown[]) => ({
  data,
  pagination: { page: 1, pageSize: 100, totalItems: data.length, totalPages: 1 },
});

const previewBodies: Array<Record<string, unknown>> = [];
const tierBodies: Array<Record<string, unknown>> = [];
const tierPatches: Array<{ tierId: string; body: Record<string, unknown> }> = [];

function handlers() {
  return [
    http.get("/api/auth/me", () => HttpResponse.json({ username: "owner", role: "admin", authRequired: true, needsEmail: false, emailVerified: true, googleLinked: false })),
    http.get("/api/admin/quota-summary", () => HttpResponse.json({ monthlySpendMicros: 125000000, monthlyCapMicros: 500000000, remainingMicros: 375000000, unpricedCallCount: 2, nextResetAt: "2026-08-01T00:00:00Z" })),
    http.get("/api/admin/quota-tiers", () => HttpResponse.json(page([
      { id: "FREE", name: "Free", cycleUnit: "WEEK", cycleCount: 1, allowanceMicros: 1000000, isDefault: true, archivedAt: null, memberCount: 1, spendMicros: 250000 },
      { id: "TEAM", name: "Team", cycleUnit: "MONTH", cycleCount: 1, allowanceMicros: 5000000, isDefault: false, archivedAt: null, memberCount: 0, spendMicros: 0 },
    ]))),
    http.get("/api/admin/quota-accounts", () => HttpResponse.json(page([{ userId: "alice0000000", username: "alice", disabled: false, tierId: "FREE", allowanceMicros: 1000000, overrideMicros: null, spentMicros: 250000, recurringRemainingMicros: 750000, creditBalanceMicros: 50000, remainingMicros: 800000, overageMicros: 0, periodStart: "2026-07-30T00:00:00Z", periodEnd: "2026-08-06T00:00:00Z", status: "ACTIVE", sharedCostMicros: 250000, byokCostMicros: 40000, totalTokens: 12345 }]))),
    http.get("/api/admin/quota-accounts/:userId/ledger", () => HttpResponse.json(page([]))),
    http.get("/api/admin/llm-rates", () => HttpResponse.json(page([]))),
    http.get("/api/admin/quota-operations", () => HttpResponse.json(page([]))),
    http.post("/api/admin/quota-tiers", async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      tierBodies.push(body);
      return HttpResponse.json({
        id: body.id,
        name: body.name,
        cycleUnit: body.cycleUnit,
        cycleCount: body.cycleCount,
        allowanceMicros: body.allowanceMicros,
        isDefault: false,
        archivedAt: null,
        memberCount: 0,
        spendMicros: 0,
      }, { status: 201 });
    }),
    http.patch("/api/admin/quota-tiers/:tierId", async ({ params, request }) => {
      const body = await request.json() as Record<string, unknown>;
      tierPatches.push({ tierId: String(params.tierId), body });
      return HttpResponse.json({
        id: params.tierId,
        name: body.name ?? "Free",
        cycleUnit: body.cycleUnit ?? "WEEK",
        cycleCount: body.cycleCount ?? 1,
        allowanceMicros: body.allowanceMicros ?? 1000000,
        isDefault: params.tierId === "FREE",
        archivedAt: null,
        memberCount: 0,
        spendMicros: 0,
      });
    }),
    http.post("/api/admin/quota-operation-previews", async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      previewBodies.push(body);
      const targetType = body.targetType as string;
      return HttpResponse.json({
        id: `preview-${previewBodies.length}`,
        targetType,
        targetValue: body.targetValue ?? null,
        actionType: body.actionType,
        amountMicros: body.amountMicros,
        affectedCount: targetType === "ALL_MEMBERS" ? 1 : 1,
        totalEffectMicros: body.amountMicros ?? 0,
        expiresAt: "2026-07-30T12:15:00Z",
      }, { status: 201 });
    }),
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

async function choose(user: ReturnType<typeof userEvent.setup>, triggerName: string, optionName: string | RegExp) {
  await user.click(screen.getByRole("combobox", { name: triggerName }));
  await user.click(await screen.findByRole("option", { name: optionName }));
}

beforeEach(() => {
  previewBodies.length = 0;
  tierBodies.length = 0;
  tierPatches.length = 0;
});

describe("AdminQuotasPage", () => {
  it("keeps member actions with members and sends canonical member and all-member targets", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("heading", { name: "Cost quotas" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View my usage" })).toHaveAttribute("href", "/account");
    expect(screen.getByText(/administrators are quota-exempt/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Member balance operation" })).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Search members" }), "missing");
    expect(screen.queryByRole("cell", { name: "alice" })).not.toBeInTheDocument();
    await user.clear(screen.getByRole("textbox", { name: "Search members" }));
    await user.click(screen.getByRole("button", { name: "Manage" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("persistent allowance override");
    await user.click(screen.getByRole("button", { name: "Close" }));

    await choose(user, "Target member", /alice · FREE/);
    expect(screen.getByRole("combobox", { name: "Target member" })).toHaveTextContent("alice");
    expect(screen.getByRole("combobox", { name: "Target member" })).not.toHaveTextContent("alice0000000");
    await user.type(screen.getByLabelText("Amount (USD)"), "1.00");
    await user.click(screen.getByRole("button", { name: "Preview impact" }));
    await waitFor(() => expect(previewBodies).toHaveLength(1));
    expect(previewBodies[0]).toEqual({
      targetType: "USER",
      targetValue: "alice0000000",
      actionType: "GRANT_CREDIT",
      amountMicros: 1000000,
    });

    await choose(user, "Target scope", "All members");
    await user.click(screen.getByRole("button", { name: "Preview impact" }));
    await waitFor(() => expect(previewBodies).toHaveLength(2));
    expect(previewBodies[1]).toEqual({
      targetType: "ALL_MEMBERS",
      actionType: "GRANT_CREDIT",
      amountMicros: 1000000,
    });
  });

  it("creates a tier from the roster with an admin-supplied short ID", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Cost quotas" });

    await user.click(screen.getByRole("tab", { name: "Tiers" }));
    expect(await screen.findByRole("heading", { name: "Allowance tiers" })).toBeInTheDocument();
    // Every mutation carries its own reason; there is no shared reason field.
    expect(screen.queryByLabelText("Audit reason for the next tier action")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tier name")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New tier" }));
    await user.type(screen.getByLabelText("Tier name"), "Partner Team");
    // The short ID follows the name until it is edited.
    expect(screen.getByLabelText("Short ID")).toHaveValue("PARTNER_TEAM");
    await user.clear(screen.getByLabelText("Short ID"));
    await user.type(screen.getByLabelText("Short ID"), "partners");
    expect(screen.getByLabelText("Short ID")).toHaveValue("PARTNERS");
    await user.type(screen.getByLabelText("Reason for this new tier"), "new partner plan");
    await user.click(screen.getByRole("button", { name: "Create tier" }));
    await waitFor(() => expect(tierBodies).toHaveLength(1));
    expect(tierBodies[0]).toMatchObject({
      id: "PARTNERS",
      name: "Partner Team",
      cycleUnit: "MONTH",
      cycleCount: 1,
      allowanceMicros: null,
      reason: "new partner plan",
    });
  });

  it("edits a tier in place and refuses to archive the default tier", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Cost quotas" });
    await user.click(screen.getByRole("tab", { name: "Tiers" }));
    await screen.findByRole("heading", { name: "Allowance tiers" });

    await user.click(screen.getByRole("button", { name: "Edit Free tier" }));
    const editor = screen.getByLabelText("Tier name").closest<HTMLElement>("div.border-t");
    expect(editor).not.toBeNull();
    // The short ID is permanent, so it is a readout rather than an input here.
    expect(within(editor!).queryByRole("textbox", { name: "Short ID" })).not.toBeInTheDocument();
    // FREE is the default tier and cannot be archived.
    expect(within(editor!).queryByRole("button", { name: /Archive/ })).not.toBeInTheDocument();

    // The editor seeds from the tier it belongs to, so $1.00 is already there.
    expect(screen.getByLabelText("Allowance (USD)")).toHaveValue("1");
    await user.clear(screen.getByLabelText("Allowance (USD)"));
    await user.type(screen.getByLabelText("Allowance (USD)"), "2");
    await user.type(screen.getByLabelText("Reason for this tier change"), "raise the free allowance");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(tierPatches).toHaveLength(1));
    expect(tierPatches[0]).toEqual({
      tierId: "FREE",
      body: { reason: "raise the free allowance", allowanceMicros: 2000000 },
    });

    await user.click(screen.getByRole("button", { name: "Edit Team tier" }));
    expect(screen.getByRole("button", { name: /Archive tier/ })).toBeInTheDocument();
  });

  it("targets a tier balance operation with one inline audit reason", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Cost quotas" });

    await user.click(screen.getByRole("tab", { name: "Tiers" }));
    expect(await screen.findByRole("heading", { name: "Tier balance operation" })).toBeInTheDocument();
    expect(screen.getAllByLabelText("Reason for this operation")).toHaveLength(1);

    await choose(user, "Target tier", /Free · 1 members/);
    // The trigger shows the tier name, never the raw identifier.
    expect(screen.getByRole("combobox", { name: "Target tier" })).toHaveTextContent("Free");
    await user.type(screen.getByLabelText("Amount (USD)"), "2.50");
    await user.click(screen.getByRole("button", { name: "Preview impact" }));
    await waitFor(() => expect(previewBodies).toHaveLength(1));
    expect(previewBodies[0]).toEqual({
      targetType: "TIER",
      targetValue: "FREE",
      actionType: "GRANT_CREDIT",
      amountMicros: 2500000,
    });
  });

  it("has no automated accessibility violations in the default console", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("heading", { name: "Cost quotas" })).toBeInTheDocument();
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
