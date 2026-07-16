import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { AddSkillPopover } from "./AddSkillPopover";

describe("AddSkillPopover", () => {
  it("adds a brand-new skill with the chosen category", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/profile/skills", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          id: "e1",
          kind: "new_skill",
          addedAt: "2026-07-16T00:00:00Z",
          name: "Rust",
          category: "hard",
        });
      }),
    );
    const user = userEvent.setup();
    render(<AddSkillPopover skillName="Rust" />, { wrapper: withQueryClient });

    await user.click(screen.getByRole("button", { name: /add "rust" to your profile/i }));
    await user.click(screen.getByRole("button", { name: /add to my skills/i }));

    await waitFor(() => expect(body).toEqual({ name: "Rust", category: null }));
  });

  it("attaches the skill as an alias to an existing skill", async () => {
    let aliasPath = "";
    let aliasBody: unknown;
    server.use(
      http.get("*/api/profile/skills", () =>
        HttpResponse.json([{ id: "s1", name: "Python", category: null }]),
      ),
      http.post("*/api/profile/skills/:skillId/aliases", async ({ request, params }) => {
        aliasPath = String(params.skillId);
        aliasBody = await request.json();
        return HttpResponse.json({
          id: "e2",
          kind: "alias",
          addedAt: "2026-07-16T00:00:00Z",
          aliasText: "Python3",
          targetSkillDisplay: "Python",
        });
      }),
    );
    const user = userEvent.setup();
    render(<AddSkillPopover skillName="Python3" />, { wrapper: withQueryClient });

    await user.click(screen.getByRole("button", { name: /add "python3" to your profile/i }));
    await user.click(screen.getByRole("button", { name: /same as a skill i have/i }));
    await screen.findByText("Python");
    await user.click(screen.getByText("Python"));

    await waitFor(() => expect(aliasPath).toBe("s1"));
    expect(aliasBody).toEqual({ alias: "Python3" });
  });
});
