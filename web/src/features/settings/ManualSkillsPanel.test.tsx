import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { ManualSkillsPanel } from "./ManualSkillsPanel";

describe("ManualSkillsPanel", () => {
  it("renders nothing when there are no manual entries", async () => {
    server.use(
      http.get("*/api/profile/manual-skills", () => HttpResponse.json([])),
    );
    const { container } = render(<ManualSkillsPanel />, { wrapper: withQueryClient });

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("lists entries and removes one on delete", async () => {
    let deletedId = "";
    server.use(
      http.get("*/api/profile/manual-skills", () =>
        HttpResponse.json([
          { id: "e1", kind: "new_skill", addedAt: "2026-07-16T00:00:00Z", name: "Rust" },
          {
            id: "e2",
            kind: "alias",
            addedAt: "2026-07-16T00:00:00Z",
            aliasText: "Python3",
            targetSkillDisplay: "Python",
          },
        ]),
      ),
      http.delete("*/api/profile/manual-skills/:entryId", ({ params }) => {
        deletedId = String(params.entryId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    render(<ManualSkillsPanel />, { wrapper: withQueryClient });

    await screen.findByText("Rust");
    expect(screen.getByText("Python3 → Python")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /remove rust/i }));

    await waitFor(() => expect(deletedId).toBe("e1"));
  });
});
