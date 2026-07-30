import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
});
