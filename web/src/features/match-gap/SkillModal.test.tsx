import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";

import { server } from "@/test/server";
import type { SkillRow } from "./aggregate";
import { SkillModal } from "./SkillModal";

const skill: SkillRow = {
  key: "python",
  skill: "Python",
  domainId: "backend",
  covered: false,
  coverage: "adjacent",
  score: 9,
  jobCount: 3,
  must: 2,
  nice: 1,
  tech: 0,
  members: { Python: 2, python3: 1 },
};

it("shows evidence and loads suggestions by stable key", async () => {
  let requestedKey: string | null = null;
  server.use(
    http.get("/api/suggestions", ({ request }) => {
      requestedKey = new URL(request.url).searchParams.get("key");
      return HttpResponse.json({ suggestion: null, stale: false });
    }),
  );

  render(
    <QueryClientProvider client={new QueryClient()}>
      <SkillModal
        skill={skill}
        domainLabel="Backend"
        state="none"
        jobs={[{ id: 1, company: "Acme", title: "Backend Engineer", seniority: "senior" }]}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: "Python" })).toBeInTheDocument();
  expect(screen.getByText("Adjacent")).toBeInTheDocument();
  expect(screen.getByText("python3")).toBeInTheDocument();
  expect(screen.getByText("2 jobs", { exact: false })).toBeInTheDocument();
  await waitFor(() => expect(requestedKey).toBe("python"));
});
