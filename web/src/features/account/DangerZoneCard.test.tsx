import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { DangerZoneCard } from "./DangerZoneCard";

async function openConfirmedDialog() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Reset data" }));
  await user.type(screen.getByLabelText(/type reset/i), "RESET");
  return user;
}

describe("DangerZoneCard", () => {
  it("gates reset and disarms confirmation when the dialog is dismissed", async () => {
    const user = userEvent.setup();
    render(<DangerZoneCard />);

    expect(screen.queryByRole("button", { name: "Export backup first" })).toBeNull();
    expect(screen.getByRole("button", { name: /^jobs:/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: /profile sources/i }));
    await user.click(screen.getByRole("button", { name: "Reset data" }));
    expect(
      screen.getByRole("button", { name: "Export backup first" }),
    ).toBeEnabled();
    const submit = screen.getByRole("button", { name: "Erase selected data" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/type reset/i), "RESET");
    expect(submit).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "Reset data" }));
    expect(screen.getByRole("button", { name: "Erase selected data" })).toBeDisabled();
  });

  it("posts the selected scope and reloads after a clean reset", async () => {
    const reload = vi.fn();
    let requestUrl = "";
    let requestBody: unknown;
    server.use(
      http.post("*/api/account/reset", async ({ request }) => {
        requestUrl = request.url;
        requestBody = await request.json();
        return HttpResponse.json({
          scope: "all",
          rowsDeleted: { jobs: 1 },
          areasCleared: ["output"],
          failures: {},
        });
      }),
    );
    const user = userEvent.setup();
    render(<DangerZoneCard reloadPage={reload} />);
    await user.click(screen.getByRole("button", { name: /everything/i }));
    await openConfirmedDialog();

    await user.click(screen.getByRole("button", { name: "Erase selected data" }));

    await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    expect(new URL(requestUrl).searchParams.get("confirm")).toBe("RESET");
    expect(requestBody).toEqual({ scope: "all" });
  });

  it("keeps a partial failure visible and immediately retryable", async () => {
    const reload = vi.fn();
    const warning = vi.spyOn(toast, "warning").mockImplementation(() => "toast-id");
    server.use(
      http.post("*/api/account/reset", () =>
        HttpResponse.json({
          scope: "jobs",
          rowsDeleted: { jobs: 1 },
          areasCleared: ["runs", "progress", "connector_runs"],
          failures: { "output/locked.pdf": "locked" },
        }),
      ),
    );
    const user = await openConfirmedDialogAfterRender(reload);

    await user.click(screen.getByRole("button", { name: "Erase selected data" }));

    await waitFor(() => expect(warning).toHaveBeenCalledOnce());
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/type reset/i)).toHaveValue("RESET");
    expect(screen.getByRole("button", { name: "Erase selected data" })).toBeEnabled();
  });
});

async function openConfirmedDialogAfterRender(reloadPage: () => void) {
  render(<DangerZoneCard reloadPage={reloadPage} />);
  return openConfirmedDialog();
}
