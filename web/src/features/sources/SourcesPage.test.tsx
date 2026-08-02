import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    limit: 10,
  },
  {
    id: "adzuna",
    kind: "adzuna",
    type: "aggregator",
    displayName: "Adzuna",
    enabled: true,
    pullable: false,
    detail: "US - no API key",
    limit: null,
  },
  {
    id: "ashby:openai",
    kind: "ashby",
    type: "board",
    displayName: "OpenAI",
    enabled: true,
    pullable: true,
    detail: "openai",
    limit: null,
  },
  {
    id: "workday:12345678",
    kind: "workday",
    type: "board",
    displayName: "General Motors",
    enabled: true,
    pullable: true,
    detail: "https://gm.wd5.myworkdayjobs.com/Careers",
    limit: null,
  },
  {
    id: "bamboohr:87654321",
    kind: "bamboohr",
    type: "board",
    displayName: "Acme",
    enabled: false,
    pullable: false,
    detail: "https://acme.bamboohr.com/careers",
    limit: 20,
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
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("General Motors")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("ashby")).toBeInTheDocument();
    expect(screen.getByText("workday")).toBeInTheDocument();
    expect(screen.getByText("bamboohr")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask the Scout" })).toHaveAttribute("href", "/scout");
    expect(screen.queryByRole("button", { name: /discover companies/i })).not.toBeInTheDocument();
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

  it("shows and commits a per-source limit", async () => {
    const requests: unknown[] = [];
    server.use(
      http.patch("/api/sources/:sourceId", async ({ request }) => {
        requests.push(await request.json());
        return HttpResponse.json({ ...sources[0], limit: 25 });
      }),
    );
    render(<SourcesPage />, { wrapper: withQueryClient });

    const input = await screen.findByRole("spinbutton", {
      name: "Per-pull job limit for Anthropic",
    });
    expect(input).toHaveValue(10);
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);

    await waitFor(() => expect(requests).toEqual([{ limit: 25 }]));
  });

  it("restores the canonical limit when a mutation fails", async () => {
    server.use(
      http.patch("/api/sources/:sourceId", () =>
        HttpResponse.json(
          { error: { code: "SOURCE_ERROR", message: "write failed" } },
          { status: 500 },
        ),
      ),
    );
    render(<SourcesPage />, { wrapper: withQueryClient });

    const input = await screen.findByRole("spinbutton", {
      name: "Per-pull job limit for Anthropic",
    });
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);

    await waitFor(() => expect(input).toHaveValue(10));
  });
});
