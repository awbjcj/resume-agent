import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { SecurityCard } from "./SecurityCard";

describe("SecurityCard", () => {
  it("shows Google state and the global session action", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: "owner", email: "o@example.com", googleLinked: true, authRequired: true }),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><SecurityCard /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/google is linked/i)).toBeInTheDocument();
    const revoke = screen.getByRole("button", { name: /sign out everywhere/i });
    expect(revoke).toBeInTheDocument();
    await userEvent.click(revoke);
    expect(screen.getByRole("alertdialog")).toHaveTextContent(/every existing session/i);
  });
});
