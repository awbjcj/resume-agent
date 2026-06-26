import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { AddSourceDialog } from "./AddSourceDialog";

describe("AddSourceDialog", () => {
  it("enables Add only after a successful preview", async () => {
    server.use(
      http.post("/api/sources/preview", () =>
        HttpResponse.json({ ok: true, url: "https://jobs.ashbyhq.com/x", kind: "ashby", roleCount: 7 }),
      ),
    );

    render(<AddSourceDialog />, { wrapper: withQueryClient });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    fireEvent.change(screen.getByLabelText(/careers or board url/i), {
      target: { value: "https://jobs.ashbyhq.com/x" },
    });
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/7 roles/i)).toBeInTheDocument());
    const addButtons = screen.getAllByRole("button", { name: "Add source" });
    expect(addButtons[addButtons.length - 1]).not.toBeDisabled();
  });
});
