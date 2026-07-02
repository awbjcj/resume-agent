import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { DeskHealth } from "./DeskHealth";

const STATUS = {
  secrets: { anthropicKey: true, anyLlmKey: true },
  profile: {
    documentCount: 1,
    hasResume: true,
    factsBuiltAt: null,
    githubUsername: null,
  },
  search: { configured: false },
  sources: { enabledCount: 0 },
  complete: false,
};

function renderHealth() {
  return render(
    <MemoryRouter>
      <DeskHealth />
    </MemoryRouter>,
    { wrapper: withQueryClient },
  );
}

describe("DeskHealth", () => {
  it("links each incomplete line to its settings page", async () => {
    server.use(http.get("/api/setup/status", () => HttpResponse.json(STATUS)));
    renderHealth();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /search/i })).toHaveAttribute(
        "href",
        "/settings/search",
      ),
    );
    expect(screen.getByRole("link", { name: /sources/i })).toHaveAttribute(
      "href",
      "/settings/sources",
    );
    expect(screen.getByRole("link", { name: /resume setup/i })).toHaveAttribute(
      "href",
      "/setup",
    );
  });

  it("shows the ready state when setup is complete", async () => {
    server.use(
      http.get("/api/setup/status", () =>
        HttpResponse.json({
          ...STATUS,
          profile: { ...STATUS.profile, factsBuiltAt: "2026-07-01T00:00:00Z" },
          search: { configured: true },
          sources: { enabledCount: 2 },
          complete: true,
        }),
      ),
    );
    renderHealth();
    await waitFor(() =>
      expect(screen.getByText(/desk is ready/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("link", { name: /resume setup/i }),
    ).not.toBeInTheDocument();
  });

  it("shows ready when complete via a non-Anthropic LLM key", async () => {
    // Backend completeness is provider-agnostic (any_llm_key); the checklist
    // must not perpetually flag a working non-Anthropic setup as broken.
    server.use(
      http.get("/api/setup/status", () =>
        HttpResponse.json({
          secrets: { anthropicKey: false, anyLlmKey: true },
          profile: { documentCount: 1, hasResume: true, factsBuiltAt: "2026-07-01T00:00:00Z", githubUsername: null },
          search: { configured: true },
          sources: { enabledCount: 2 },
          complete: true,
        }),
      ),
    );
    renderHealth();
    await waitFor(() =>
      expect(screen.getByText(/desk is ready/i)).toBeInTheDocument(),
    );
  });

  it("renders nothing when the status endpoint errors", async () => {
    server.use(
      http.get("*/api/setup/status", () =>
        HttpResponse.json(
          { error: { code: "X", message: "boom" } },
          { status: 500 },
        ),
      ),
    );
    const { container } = renderHealth();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
