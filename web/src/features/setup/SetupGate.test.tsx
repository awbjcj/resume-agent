import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { SetupGate } from "./SetupGate";

const INCOMPLETE = {
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false }, sources: { enabledCount: 0 }, complete: false,
};

function renderGate() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<SetupGate><div>dashboard</div></SetupGate>} />
        <Route path="/setup" element={<div>wizard</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient },
  );
}

describe("SetupGate", () => {
  beforeEach(() => localStorage.clear());

  it("redirects to /setup when setup is incomplete", async () => {
    server.use(http.get("/api/setup/status", () => HttpResponse.json(INCOMPLETE)));
    renderGate();
    await waitFor(() => expect(screen.getByText("wizard")).toBeInTheDocument());
  });

  it("does not redirect when the user dismissed setup", async () => {
    server.use(http.get("/api/setup/status", () => HttpResponse.json(INCOMPLETE)));
    localStorage.setItem("resume-tailor-harness-setup-dismissed", "1");
    renderGate();
    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
  });

  it("fails open when the status endpoint errors", async () => {
    server.use(http.get("/api/setup/status", () =>
      HttpResponse.json({ error: { code: "X", message: "boom" } }, { status: 500 })));
    renderGate();
    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
  });
});
