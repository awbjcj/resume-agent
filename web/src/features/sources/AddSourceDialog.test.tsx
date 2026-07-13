import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    fireEvent.click(screen.getByRole("button", { name: /verify connection/i }));

    await waitFor(() => expect(screen.getByText(/7 matching roles/i)).toBeInTheDocument());
    const addButtons = screen.getAllByRole("button", { name: "Add source" });
    expect(addButtons[addButtons.length - 1]).not.toBeDisabled();
  });

  it("uses native provider fields and sends the provider recipe", async () => {
    const requests: unknown[] = [];
    server.use(
      http.post("/api/sources/preview", async ({ request }) => {
        requests.push(await request.json());
        return HttpResponse.json({
          ok: true,
          url: "https://jobs.ashbyhq.com/acme",
          kind: "ashby",
          roleCount: 4,
        });
      }),
    );
    const user = userEvent.setup();

    render(<AddSourceDialog />, { wrapper: withQueryClient });
    await user.click(screen.getByRole("button", { name: "Add source" }));
    const provider = screen.getByRole("combobox", { name: /connection type/i });
    fireEvent.keyDown(provider, { key: "ArrowDown" });
    await user.click(await screen.findByText("Ashby"));
    await user.type(screen.getByLabelText(/organization slug/i), "acme");
    await user.click(screen.getByRole("button", { name: /verify connection/i }));

    await waitFor(() => expect(screen.getByText(/4 matching roles/i)).toBeInTheDocument());
    expect(requests).toEqual([
      { provider: "ashby", token: "acme", country: "com", label: null },
    ]);
    expect(screen.queryByLabelText(/careers or board url/i)).not.toBeInTheDocument();
  });
});
