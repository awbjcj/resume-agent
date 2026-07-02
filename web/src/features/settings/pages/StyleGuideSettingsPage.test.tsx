import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { StyleGuideSettingsPage } from "./StyleGuideSettingsPage";

describe("StyleGuideSettingsPage", () => {
  it("edits and saves the markdown content", async () => {
    let lastPut: { content: string } | null = null;
    server.use(
      http.get("/api/config/style-guide", () => HttpResponse.json({ content: "# Voice" })),
      http.put("/api/config/style-guide", async ({ request }) => {
        lastPut = (await request.json()) as { content: string };
        return HttpResponse.json(lastPut);
      }),
    );

    const user = userEvent.setup();
    render(<StyleGuideSettingsPage />, { wrapper: withQueryClient });
    const box = await waitFor(() => screen.getByLabelText("Style guide"));
    await user.type(box, "\nBe concrete.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(lastPut?.content).toContain("Be concrete."));
  });
});
