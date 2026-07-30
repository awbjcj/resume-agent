import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { AuthGate } from "./AuthGate";
import { LoginPage } from "./LoginPage";
import { RegisterPage } from "./RegisterPage";
import { LogoutButton } from "./LogoutButton";

function wrap(ui: ReactNode, initialPath = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/login" element={<div>Login route</div>} />
          <Route path="/complete-profile" element={<div>Complete profile</div>} />
          <Route path="/" element={<AuthGate>{ui}</AuthGate>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AuthGate", () => {
  it.each([
    { state: { username: null, authRequired: false }, label: "open mode" },
    { state: { username: "owner", authRequired: true }, label: "signed in" },
  ])("renders children in $label", async ({ state }) => {
    server.use(http.get("/api/auth/me", () => HttpResponse.json(state)));
    wrap(<div>App content</div>);
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("redirects to login when a session is required", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: null, authRequired: true }),
      ),
    );
    wrap(<div>App content</div>);
    expect(await screen.findByText("Login route")).toBeInTheDocument();
  });

  it("redirects legacy accounts to complete their profile", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: "owner", authRequired: true, needsEmail: true }),
      ),
    );
    wrap(<div>App content</div>);
    expect(await screen.findByText("Complete profile")).toBeInTheDocument();
  });

  it("fails closed with a retry action on network errors", async () => {
    let attempts = 0;
    server.use(
      http.get("/api/auth/me", () => {
        attempts += 1;
        if (attempts === 1) return HttpResponse.error();
        return HttpResponse.json({ username: null, authRequired: false });
      }),
    );
    const user = userEvent.setup();
    wrap(<div>App content</div>);
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  it("shows the server error for rejected credentials", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { error: { code: "UNAUTHORIZED", message: "Invalid username or password" } },
          { status: 401 },
        ),
      ),
    );
    const client = new QueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/login"]}>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.type(screen.getByLabelText(/email/i), "owner@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid username or password",
    );
  });
});

describe("LogoutButton", () => {
  it("is hidden in open mode", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: null, authRequired: false }),
      ),
    );
    wrap(<LogoutButton />);
    expect(await screen.findByText("App content").catch(() => null)).toBeNull();
    expect(screen.queryByRole("button", { name: /sign out/i })).toBeNull();
  });
});

describe("RegisterPage", () => {
  it("submits invite registration and opens email verification", async () => {
    let registered = false;
    server.use(
      http.post("/api/auth/register", () => {
        registered = true;
        return HttpResponse.json({ status: "sent" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/register"]}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify-email" element={<div>Verify route</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.type(screen.getByLabelText(/^email$/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "long-safe-password-42");
    await user.type(screen.getByLabelText(/invite code/i), "inv_example");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(registered).toBe(true);
    expect(await screen.findByText("Verify route")).toBeInTheDocument();
  });
});
