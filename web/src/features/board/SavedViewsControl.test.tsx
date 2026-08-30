import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";
import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";

import { SavedViewsControl } from "./SavedViewsControl";

describe("SavedViewsControl", () => {
  it("applies a saved query through the canonical filter parser", async () => {
    server.use(
      http.get("/api/board-views", () =>
        HttpResponse.json([
          {
            id: 1,
            board: "shortlist",
            name: "Remote leaders",
            queryString: "q=platform&remote=remote&fitMin=80",
            createdAt: "2026-08-29T00:00:00Z",
            updatedAt: "2026-08-29T00:00:00Z",
          },
        ]),
      ),
    );
    const onApply = vi.fn();
    render(
      <SavedViewsControl
        board="shortlist"
        filter={emptyFilterState()}
        defaultSort="fit"
        onApply={onApply}
      />,
      { wrapper: withQueryClient },
    );

    fireEvent.click(screen.getByRole("button", { name: "Views" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remote leaders" }));

    await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
    const applied = onApply.mock.calls[0][0];
    expect(applied.q).toBe("platform");
    expect(applied.fitMin).toBe(80);
    expect([...applied.remote]).toEqual(["remote"]);
  });

  it("round-trips board-specific query state without adding a second filter model", async () => {
    let savedQuery = "";
    server.use(
      http.get("/api/board-views", () =>
        HttpResponse.json([
          {
            id: 2,
            board: "triage",
            name: "Archived jobs",
            queryString: "archived=1",
            createdAt: "2026-08-29T00:00:00Z",
            updatedAt: "2026-08-29T00:00:00Z",
          },
        ]),
      ),
      http.post("/api/board-views", async ({ request }) => {
        const body = await request.json() as { queryString: string };
        savedQuery = body.queryString;
        return HttpResponse.json({ id: 3, ...body }, { status: 201 });
      }),
    );
    const onApply = vi.fn();
    render(
      <SavedViewsControl
        board="triage"
        filter={emptyFilterState()}
        defaultSort="recency"
        extraQuery={{ archived: "1" }}
        onApply={onApply}
      />,
      { wrapper: withQueryClient },
    );

    fireEvent.click(screen.getByRole("button", { name: "Views" }));
    fireEvent.click(await screen.findByRole("button", { name: "Archived jobs" }));
    await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
    expect(onApply.mock.calls[0][1].get("archived")).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: "Views" }));
    fireEvent.change(screen.getByRole("textbox", { name: "View name" }), {
      target: { value: "Archived only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(savedQuery).toContain("archived=1"));
  });
});
