import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { BackupSettingsPage } from "./BackupSettingsPage";

const applied = vi.fn();

function mockHandlers() {
  server.use(
    http.get("*/api/settings/sections", () =>
      HttpResponse.json({
        sections: [
          { id: "sources", label: "Company sources", customized: true },
          { id: "prune", label: "Pruning", customized: false },
        ],
      }),
    ),
    http.post("*/api/settings/bundle/preview", () =>
      HttpResponse.json({
        version: 1,
        exportedAt: "2026-07-23T00:00:00+00:00",
        sections: [{ id: "sources", label: "Company sources", customized: true }],
        unknownSections: [],
      }),
    ),
    http.post("*/api/settings/bundle", () => {
      applied();
      return HttpResponse.json({ applied: ["sources"] });
    }),
  );
}

describe("BackupSettingsPage", () => {
  afterEach(() => {
    applied.mockClear();
    vi.restoreAllMocks();
  });

  it("lists every section with its customized state", async () => {
    mockHandlers();
    render(<BackupSettingsPage />, { wrapper: withQueryClient });
    expect(await screen.findByText("Company sources")).toBeInTheDocument();
    expect(screen.getByText("Pruning")).toBeInTheDocument();
    expect(screen.getByText("Customized")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
  });

  it("offers a reset control per section", async () => {
    mockHandlers();
    render(<BackupSettingsPage />, { wrapper: withQueryClient });
    await screen.findByText("Company sources");
    expect(
      screen.getAllByRole("button", { name: /reset to defaults/i }),
    ).toHaveLength(2);
  });

  it("previews a chosen bundle before applying it", async () => {
    mockHandlers();
    const user = userEvent.setup();
    render(<BackupSettingsPage />, { wrapper: withQueryClient });
    await screen.findByText("Company sources");

    const file = new File(["x"], "bundle.tar.gz", { type: "application/gzip" });
    await user.upload(screen.getByLabelText(/bundle file/i), file);

    expect(
      await screen.findByText(/this bundle will replace/i),
    ).toBeInTheDocument();
    expect(applied).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /apply bundle/i }));
    await waitFor(() => expect(applied).toHaveBeenCalled());
  });
});
