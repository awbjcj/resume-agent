import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { ResetSectionButton } from "./ResetSectionButton";

describe("ResetSectionButton", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not reset until the dialog is confirmed", async () => {
    const reset = vi.fn();
    server.use(
      http.post("*/api/settings/sections/:id/reset", ({ params }) => {
        reset(params.id);
        return HttpResponse.json({
          id: params.id,
          label: "Company sources",
          customized: false,
        });
      }),
    );
    const user = userEvent.setup();
    render(<ResetSectionButton sectionId="sources" label="Company sources" />, {
      wrapper: withQueryClient,
    });

    await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
    expect(reset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /^reset$/i }));
    await waitFor(() => expect(reset).toHaveBeenCalledWith("sources"));
  });

  it("names the section it will reset", async () => {
    const user = userEvent.setup();
    render(<ResetSectionButton sectionId="sources" label="Company sources" />, {
      wrapper: withQueryClient,
    });

    await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
    expect(
      screen.getByText(/reset company sources to defaults/i),
    ).toBeInTheDocument();
  });

  it("cancelling leaves the section untouched", async () => {
    const reset = vi.fn();
    server.use(
      http.post("*/api/settings/sections/:id/reset", ({ params }) => {
        reset(params.id);
        return HttpResponse.json({
          id: params.id,
          label: "Company sources",
          customized: false,
        });
      }),
    );
    const user = userEvent.setup();
    render(<ResetSectionButton sectionId="sources" label="Company sources" />, {
      wrapper: withQueryClient,
    });

    await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(reset).not.toHaveBeenCalled();
  });
});
