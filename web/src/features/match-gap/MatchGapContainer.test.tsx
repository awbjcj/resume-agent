import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { MatchGapContainer } from "./MatchGapContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("MatchGapContainer", () => {
  it("lists missing skills with demand share", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({
          targetTotal: 4,
          gaps: [{ skill: "Kubernetes", demandCount: 3, targetTotal: 4, demandShare: 75 }],
        }),
      ),
    );
    wrap(<MatchGapContainer />);
    await waitFor(() => expect(screen.getByText("Kubernetes")).toBeInTheDocument());
    expect(screen.getByText("75")).toBeInTheDocument();
  });

  it("shows no-profile empty state when targetTotal is 0", async () => {
    server.use(
      http.get("/api/match-gap", () => HttpResponse.json({ targetTotal: 0, gaps: [] })),
    );
    wrap(<MatchGapContainer />);
    await waitFor(() => expect(screen.getByText(/no target jobs yet/i)).toBeInTheDocument());
  });
});
