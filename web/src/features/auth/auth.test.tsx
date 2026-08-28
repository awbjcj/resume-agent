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
    {
      state: { username: "local", role: "admin", authRequired: false },
      label: "local default-user mode",
    },
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

describe("auth callback notices", () => {
  it("explains a Google sign-in that bounced back to login", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/login?error=google_conflict"]}>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/already linked/i);
  });

  it("names an unknown callback code rather than rendering a blank form", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/login?error=something_new"]}>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/didn.t complete/i);
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

  it("prefills a Google identity while keeping email registration available", async () => {
    let sent: { email?: string; displayName?: string | null } = {};
    server.use(
      http.post("/api/auth/register", async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return HttpResponse.json({ status: "sent" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter
          initialEntries={[
            "/register?from=google&email=newcomer%40umich.edu&name=New+Comer",
          ]}
        >
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify-email" element={<div>Verify route</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText(/^email$/i)).toHaveValue("newcomer@umich.edu");
    expect(screen.getByLabelText(/display name/i)).toHaveValue("New Comer");
    // Scoped by text, not by role: the password strength meter is a second
    // role="status" live region on this page.
    expect(screen.getByText(/no account matches/i)).toBeInTheDocument();
    expect(screen.getByText(/won.t need a password/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^password$/i), "long-safe-password-42");
    await user.type(screen.getByLabelText(/invite code/i), "inv_example");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Verify route")).toBeInTheDocument();
    expect(sent.email).toBe("newcomer@umich.edu");
    expect(sent.displayName).toBe("New Comer");
  });

  it("keeps the prefilled email editable", async () => {
    let sent: { email?: string } = {};
    server.use(
      http.post("/api/auth/register", async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return HttpResponse.json({ status: "sent" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/register?from=google&email=wrong%40umich.edu"]}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify-email" element={<div>Verify route</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.clear(screen.getByLabelText(/^email$/i));
    await user.type(screen.getByLabelText(/^email$/i), "right@umich.edu");
    await user.type(screen.getByLabelText(/^password$/i), "long-safe-password-42");
    await user.type(screen.getByLabelText(/invite code/i), "inv_example");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Verify route")).toBeInTheDocument();
    expect(sent.email).toBe("right@umich.edu");
  });
});
