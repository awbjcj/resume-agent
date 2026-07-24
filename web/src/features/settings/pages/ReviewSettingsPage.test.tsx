import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/test/utils";
import { ReviewSettingsPage } from "./ReviewSettingsPage";

const save = vi.fn();

vi.mock("../use-config", () => ({
  useConfig: () => ({
    data: {
      maxRounds: 3,
      scoreThreshold: 85,
      mergedAdvisory: false,
      tailorTier: "premium",
      reviserTier: "premium",
      reviewers: [],
      lengthBudget: null,
    },
  }),
  useSaveConfig: () => ({ mutate: save, isPending: false }),
}));

describe("ReviewSettingsPage pipeline controls", () => {
  it("saves merged advisory and writer tier changes", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("switch", { name: /merge advisory/i }));
    await userEvent.click(screen.getByRole("button", { name: "mid writer tier" }));
    await userEvent.click(screen.getByRole("button", { name: "cheap reviser tier" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        mergedAdvisory: true,
        tailorTier: "mid",
        reviserTier: "cheap",
      }),
    );
  });
});
