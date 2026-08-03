import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { H1BCheckButton } from "./H1BCheckButton";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

describe("H1BCheckButton", () => {
  it("updates the visible evidence status after a manual check", async () => {
    server.use(
      http.post("/api/jobs/7/h1b-sponsorship", () =>
        HttpResponse.json({
          capability: "available",
          evidence: { status: "matched" },
        }),
      ),
    );

    render(<H1BCheckButton jobId={7} company="Acme" />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Check H-1B sponsorship" }));

    await waitFor(() => expect(screen.getByText("History match")).toBeInTheDocument());
    expect(
      screen.getByRole("button", {
        name: "Check H-1B sponsorship again; current result: History match",
      }),
    ).toBeInTheDocument();
  });

  it("is unavailable when the job has no company", () => {
    render(<H1BCheckButton jobId={7} company={null} />, { wrapper });

    expect(
      screen.getByRole("button", {
        name: "Check H-1B sponsorship (company missing)",
      }),
    ).toBeDisabled();
  });
});
