import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { GoogleButton } from "./GoogleButton";

describe("GoogleButton", () => {
  it("explains why unavailable Google sign-in is disabled", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json({ status: "ok", mailConfigured: true, googleOauthConfigured: false })));
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><GoogleButton mode="login" /></QueryClientProvider>);
    const button = await screen.findByRole("button", { name: /continue with google/i });
    expect(button).toBeDisabled();
    await user.hover(button.parentElement!);
    expect(await screen.findByText(/not configured/i)).toBeInTheDocument();
  });

  it("starts Google registration with the invite and no password", async () => {
    let startUrl: URL | undefined;
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json({
          status: "ok",
          mailConfigured: true,
          googleOauthConfigured: true,
        }),
      ),
      http.get("/api/auth/google/start", ({ request }) => {
        startUrl = new URL(request.url);
        return HttpResponse.json(
          { error: { code: "TEST_STOP", message: "OAuth start captured" } },
          { status: 409 },
        );
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <GoogleButton mode="register" invite="inv_google" disabledReason="" />
      </QueryClientProvider>,
    );

    const button = await screen.findByRole("button", {
      name: /continue with google/i,
    });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);

    await waitFor(() => expect(startUrl).toBeDefined());
    expect(startUrl?.searchParams.get("mode")).toBe("register");
    expect(startUrl?.searchParams.get("invite")).toBe("inv_google");
  });
});
