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
});
