import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
import { server } from "@/test/server";
import { AnalyticsContainer } from "./AnalyticsContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("AnalyticsContainer", () => {
  it("renders an accessible source table", async () => {
    server.use(
      http.get("/api/analytics", () =>
        HttpResponse.json({
          bySource: [
            {
              label: "greenhouse",
              applications: 10,
              responses: 4,
              interviews: 2,
              offers: 1,
              responseRate: 40,
              interviewRate: 20,
              offerRate: 10,
            },
          ],
          byBand: [],
        }),
      ),
    );
    wrap(<AnalyticsContainer />);
    await waitFor(() =>
      expect(screen.getByRole("table", { name: /by source/i })).toBeInTheDocument(),
    );
    // "greenhouse" appears in the table cell and the (aria-hidden) chart axis
    expect(screen.getAllByText("greenhouse").length).toBeGreaterThan(0);
  });

  it("shows empty state when no applications", async () => {
    server.use(http.get("/api/analytics", () => HttpResponse.json({ bySource: [], byBand: [] })));
    wrap(<AnalyticsContainer />);
    await waitFor(() =>
      expect(screen.getByText(/no applications tracked/i)).toBeInTheDocument(),
    );
  });

  it("uses application-specific analytics labels in Chinese", async () => {
    await changeLanguage("zh-CN");
    server.use(
      http.get("/api/analytics", () =>
        HttpResponse.json({
          bySource: [{
            label: "greenhouse",
            applications: 10,
            responses: 4,
            interviews: 2,
            offers: 1,
            responseRate: 40,
            interviewRate: 20,
            offerRate: 10,
          }],
          byBand: [],
        }),
      ),
    );
    wrap(<AnalyticsContainer />);

    const sourceTable = await screen.findByRole("table", { name: "按来源" });
    expect(within(sourceTable).getByRole("columnheader", { name: "申请数" })).toBeInTheDocument();
    expect(screen.getByText("流程周期")).toBeInTheDocument();
  });
});
