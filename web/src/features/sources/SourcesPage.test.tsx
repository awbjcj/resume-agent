import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { SourcesPage } from "./SourcesPage";

const sources = [
  {
    id: "greenhouse:anthropic",
    kind: "greenhouse",
    type: "board",
    displayName: "Anthropic",
    enabled: true,
    pullable: true,
    detail: "anthropic",
  },
  {
    id: "adzuna",
    kind: "adzuna",
    type: "aggregator",
    displayName: "Adzuna",
    enabled: true,
    pullable: false,
    detail: "US - no API key",
  },
];

describe("SourcesPage", () => {
  beforeEach(() => {
    useRunStore.setState({ runs: {} });
    server.use(http.get("/api/sources", () => HttpResponse.json(sources)));
  });

  it("renders boards and aggregators sections", async () => {
    render(<SourcesPage />, { wrapper: withQueryClient });

    await waitFor(() =>
      expect(screen.getByText(/Boards & careers pages/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Aggregators/i)).toBeInTheDocument();
  });

  it("disables pull controls for non-pullable sources", async () => {
    render(<SourcesPage />, { wrapper: withQueryClient });

    await waitFor(() => expect(screen.getByText(/no API key/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Pull Adzuna/i })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Select Adzuna/i })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("renders the latest per-source pull result", async () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "pull",
      status: "running",
      percent: 50,
      phase: "Pulling greenhouse:anthropic",
      current: 1,
      total: 2,
      etaText: null,
      result: {
        totals: { "greenhouse:anthropic": 3 },
        upgraded: { "greenhouse:anthropic": 1 },
        skipped: { "greenhouse:anthropic": 8 },
        failures: {},
      },
    });

    render(<SourcesPage />, { wrapper: withQueryClient });

    await waitFor(() => expect(screen.getByText(/Latest pull result/i)).toBeInTheDocument());
    expect(screen.getByText("+3 added")).toBeInTheDocument();
    expect(screen.getByText("1 upd")).toBeInTheDocument();
    expect(screen.getByText("8 skip")).toBeInTheDocument();
  });
});
