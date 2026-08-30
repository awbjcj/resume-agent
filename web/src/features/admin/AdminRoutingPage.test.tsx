import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
import { server } from "@/test/server";
import { AdminRoutingPage } from "./AdminRoutingPage";

const providers = [
  { provider: "anthropic", label: "Anthropic", routeMode: "auto", effectiveMode: "subscription", configurationError: null, key: { isSet: true, hint: "1234" } },
  { provider: "openai", label: "OpenAI", routeMode: "auto", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
  { provider: "gemini", label: "Gemini", routeMode: "api", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
  { provider: "deepseek", label: "DeepSeek", routeMode: "api", effectiveMode: "api", configurationError: null, key: { isSet: false, hint: null } },
] as const;

function renderPage(savedBodies: Array<Record<string, unknown>> = [], providerData: unknown = providers) {
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json({ username: "owner", role: "admin", authRequired: true, needsEmail: false, emailVerified: true, googleLinked: false })),
    http.get("/api/admin/routing", () => HttpResponse.json({ baseUrl: "https://gateway.example.com", providers: providerData })),
    http.put("/api/admin/routing", async ({ request }) => {
      savedBodies.push(await request.json() as Record<string, unknown>);
      return HttpResponse.json({ baseUrl: "https://gateway.example.com", providers: providerData });
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
    expect(screen.getByLabelText("Anthropic route mode")).toHaveTextContent("Auto");
    expect(screen.getByLabelText("Gemini route mode")).toHaveTextContent("Direct API");
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

  it("labels the closed trigger with the same name as its option", async () => {
    const user = userEvent.setup();
    renderPage();

    const trigger = await screen.findByLabelText("Gemini route mode");
    await user.click(trigger);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Auto",
      "Subscription",
      "Direct API",
    ]);

    await user.click(within(listbox).getByRole("option", { name: "Subscription" }));
    await waitFor(() => expect(trigger).toHaveTextContent("Subscription"));
  });

  it("localizes route modes, statuses, and route-mode labels in Chinese", async () => {
    await changeLanguage("zh-CN");
    const user = userEvent.setup();
    renderPage();

    const trigger = await screen.findByLabelText("Gemini 的路由模式");
    expect(trigger).toHaveTextContent("直连 API");
    expect(screen.getAllByText("订阅网关").length).toBeGreaterThan(0);

    await user.click(trigger);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "自动选择",
      "订阅网关",
      "直连 API",
    ]);
  });

  it("localizes known provider configuration warnings in Chinese", async () => {
    await changeLanguage("zh-CN");
    renderPage([], [{
      ...providers[0],
      routeMode: "subscription",
      effectiveMode: null,
      configurationError: "anthropic is pinned to subscription mode but SUB2API_BASE_URL is unset",
    }]);

    expect(await screen.findByText("anthropic 已固定为订阅网关模式，但尚未设置 SUB2API_BASE_URL。")).toBeInTheDocument();
  });

  it("has no automated accessibility violations", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("heading", { name: "Provider routing" })).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);
  });
});
