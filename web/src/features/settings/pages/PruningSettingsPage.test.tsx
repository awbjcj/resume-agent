import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { PruningSettingsPage } from "./PruningSettingsPage";

const DOC = {
  fitThreshold: 40, staleDays: 60, retentionDays: 30,
  enableRejected: true, enableLowFit: true, enableStale: true,
};

describe("PruningSettingsPage", () => {
  it("shows SaveBar only after an edit, then PUTs the full document", async () => {
    let lastPut: typeof DOC | null = null;
    server.use(
      http.get("/api/config/prune", () => HttpResponse.json(DOC)),
      http.put("/api/config/prune", async ({ request }) => {
        lastPut = (await request.json()) as typeof DOC;
        return HttpResponse.json(lastPut);
      }),
    );

    const user = userEvent.setup();
    render(<PruningSettingsPage />, { wrapper: withQueryClient });
    await waitFor(() => expect(screen.getByLabelText("Fit threshold")).toBeInTheDocument());
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Fit threshold"));
    await user.type(screen.getByLabelText("Fit threshold"), "55");
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(lastPut).toMatchObject({ fitThreshold: 55 }));
  });
});
