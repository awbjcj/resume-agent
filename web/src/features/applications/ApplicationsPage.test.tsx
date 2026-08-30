import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
});
