import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { AdminRoutingPage } from "./AdminRoutingPage";

const providers = [
  { provider: "anthropic", label: "Anthropic", routeMode: "auto", effectiveMode: "subscription", configurationError: null, key: { isSet: true, hint: "1234" } },
  { provider: "openai", label: "OpenAI", routeMode: "auto", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
  { provider: "gemini", label: "Gemini", routeMode: "api", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
  { provider: "deepseek", label: "DeepSeek", routeMode: "api", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
] as const;

function renderPage(savedBodies: Array<Record<string, unknown>> = []) {
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json({ username: "owner", role: "admin", authRequired: true, needsEmail: false, emailVerified: true, googleLinked: false })),
    http.get("/api/admin/routing", () => HttpResponse.json({ baseUrl: "https://gateway.example.com", providers })),
    http.put("/api/admin/routing", async ({ request }) => {
      savedBodies.push(await request.json() as Record<string, unknown>);
      return HttpResponse.json({ baseUrl: "https://gateway.example.com", providers });
    }),
  );
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><AdminRoutingPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminRoutingPage", () => {
  it("shows effective routes and saves write-only key changes", async () => {
    const savedBodies: Array<Record<string, unknown>> = [];
    const user = userEvent.setup();
    renderPage(savedBodies);

    expect(await screen.findByRole("heading", { name: "Provider routing" })).toBeInTheDocument();
    expect(screen.getByText("Subscription")).toBeInTheDocument();
    expect(screen.getAllByText("Direct API").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Anthropic route mode")).toHaveTextContent("auto");
    expect(screen.getByLabelText("Gateway key", { selector: "#anthropic-gateway-key" })).toHaveAttribute("placeholder", "Configured ····1234");

    await user.click(screen.getByRole("button", { name: "Clear key" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(savedBodies).toHaveLength(1));
    expect(savedBodies[0]).toMatchObject({
      baseUrl: "https://gateway.example.com",
      anthropicKey: null,
      anthropicRouteMode: "auto",
      openaiRouteMode: "auto",
      geminiRouteMode: "api",
      deepseekRouteMode: "api",
    });
  });

  it("has no automated accessibility violations", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("heading", { name: "Provider routing" })).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
  });
});
