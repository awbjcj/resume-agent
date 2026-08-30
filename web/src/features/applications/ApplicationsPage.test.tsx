import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { changeLanguage } from "@/i18n";
import { server } from "@/test/server";
import { ApplicationsPage } from "./ApplicationsPage";

const table = {
  technicalRoundColumns: 0,
  rows: [{
    jobId: 42,
    company: "Acme",
    title: "Senior SWE",
    status: "interview",
    source: "greenhouse",
    fitScore: 82,
    overflowRounds: 0,
    customCount: 0,
    totalComp: null,
    compCurrency: null,
    offerDeadline: null,
    cells: {},
  }],
};

function renderPage() {
  server.use(http.get("/api/applications", () => HttpResponse.json(table)));
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ApplicationsPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApplicationsPage", () => {
  it("uses context-aware Chinese labels for sorting and status filters", async () => {
    await changeLanguage("zh-CN");
    renderPage();

    const sort = await screen.findByLabelText("排序方式");
    expect(sort).toHaveValue("newest");
    expect(screen.getByRole("option", { name: "最新动态" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "公司名称 A–Z" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "申请状态" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "面试中" })).toBeInTheDocument();
    expect(screen.getByText("正在显示 1 / 1 条申请记录")).toBeInTheDocument();
  });

  it("compares two selected roles using the deterministic evidence endpoint", async () => {
    await changeLanguage("en");
    const rows = [
      table.rows[0],
      { ...table.rows[0], jobId: 43, company: "Globex", title: "Staff Engineer", fitScore: null },
    ];
    server.use(
      http.get("/api/applications", () => HttpResponse.json({ ...table, rows })),
      http.post("/api/jobs/company-intelligence-comparisons", async ({ request }) => {
        expect(await request.json()).toEqual({ jobIds: [42, 43] });
        return HttpResponse.json({
          items: [
            {
              jobId: 42,
              company: "Acme",
              title: "Senior SWE",
              fitScore: 82,
              applicationStatus: "interview",
              companyEvidence: {
                state: "ready",
                retrievedAt: "2026-08-30T12:00:00Z",
                isStale: false,
                researchDepth: "deep",
                sourceCount: 4,
                strongestVerification: "corroborated",
              },
              h1BStatus: "matched",
              offerTotal: null,
              offerCurrency: null,
            },
            {
              jobId: 43,
              company: "Globex",
              title: "Staff Engineer",
              fitScore: null,
              applicationStatus: "interview",
              companyEvidence: { state: "not_researched" },
              h1BStatus: null,
              offerTotal: 210000,
              offerCurrency: "USD",
            },
          ],
        });
      }),
    );
    const user = userEvent.setup();
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><ApplicationsPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /select acme/i }));
    await user.click(screen.getByRole("checkbox", { name: /select globex/i }));
    await user.click(screen.getByRole("button", { name: "Compare selected" }));

    expect(await screen.findByRole("heading", { name: "Role comparison" })).toBeInTheDocument();
    expect(screen.getByText("deep · 4 sources · corroborated · current")).toBeInTheDocument();
    expect(screen.getByText("Not researched")).toBeInTheDocument();
    expect(screen.getByText("Historical filing match")).toBeInTheDocument();
    expect(screen.getByText("210,000 USD")).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);

    await changeLanguage("zh-CN");
    expect(await screen.findByText("深入 · 4 个来源 · 多方印证 · 当前有效")).toBeInTheDocument();
    expect(screen.getByText("找到历史申报记录")).toBeInTheDocument();
  });

  it("does not allow terminal applications to be selected for comparison", async () => {
    await changeLanguage("en");
    const rows = [
      table.rows[0],
      {
        ...table.rows[0],
        jobId: 43,
        company: "Globex",
        title: "Closed role",
        status: "rejected",
      },
    ];
    server.use(http.get("/api/applications", () => HttpResponse.json({ ...table, rows })));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><ApplicationsPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("checkbox", { name: /globex closed role is closed/i })).toBeDisabled();
  });
});
