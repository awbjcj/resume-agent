import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { SkillDrawer } from "./SkillDrawer";

function wrap(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  );
}

describe("SkillDrawer", () => {
  it("shows the display label and jobs demanding the selected target", () => {
    server.use(
      http.get("/api/suggestions", () =>
        HttpResponse.json({ suggestion: null, stale: false }),
      ),
    );
    wrap(
      <SkillDrawer
        kind="theme"
        targetKey="infra"
        label="Cloud / Infrastructure"
        jobs={[
          { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
          { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
        ]}
        onClose={() => {}}
      />,
    );

    expect(screen.getByRole("heading", { name: "Cloud / Infrastructure" })).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText(/Platform/)).toBeInTheDocument();
  });

  it("renders an explicit empty state for filtered targets", () => {
    server.use(
      http.get("/api/suggestions", () =>
        HttpResponse.json({ suggestion: null, stale: false }),
      ),
    );
    wrap(
      <SkillDrawer
        kind="skill"
        targetKey="Kubernetes"
        label="Kubernetes"
        jobs={[]}
        onClose={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/no target jobs match/i);
  });

  it("loads cached advice with the selected kind and stable key", async () => {
    let requestedKind: string | null = null;
    let requestedKey: string | null = null;
    server.use(
      http.get("/api/suggestions", ({ request }) => {
        const url = new URL(request.url);
        requestedKind = url.searchParams.get("kind");
        requestedKey = url.searchParams.get("key");
        return HttpResponse.json({ suggestion: null, stale: false });
      }),
    );
    wrap(
      <SkillDrawer
        kind="theme"
        targetKey="infra"
        label="Cloud / Infrastructure"
        jobs={[]}
        onClose={() => {}}
      />,
    );

    expect(
      await screen.findByRole("button", { name: /how to close this gap/i }),
    ).toBeInTheDocument();
    expect(requestedKind).toBe("theme");
    expect(requestedKey).toBe("infra");
  });
});
