import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  mutateAsync: vi.fn(async () => ({ runId: "r1" })),
  result: { state: "idle", result: null, error: null } as Record<string, unknown>,
}));

vi.mock("./use-search-discover", () => ({
  useDiscoverSearchTerms: () => ({ mutateAsync: state.mutateAsync, isPending: false }),
  useSearchDiscoverResult: () => state.result,
}));

import { SuggestSearchTermsDialog } from "./SuggestSearchTermsDialog";

describe("SuggestSearchTermsDialog", () => {
  beforeEach(() => {
    state.mutateAsync.mockClear();
    state.result = { state: "idle", result: null, error: null };
  });

  it("appends approved suggestions grouped by kind", async () => {
    state.result = {
      state: "done",
      error: null,
      result: {
        prompt: "platform roles",
        suggestions: [
          { value: "Rust", kind: "keyword", reason: "profile uses Rust", status: "new" },
          { value: "python", kind: "keyword", reason: "dup", status: "duplicate" },
          { value: "Staff Engineer", kind: "title", reason: "seniority", status: "new" },
        ],
      },
    };
    const onApply = vi.fn();
    render(<SuggestSearchTermsDialog onApply={onApply} />);

    await userEvent.click(
      screen.getByRole("button", { name: /suggest search terms/i }),
    );

    await userEvent.click(await screen.findByRole("checkbox", { name: /select rust/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select staff engineer/i }));
    await userEvent.click(screen.getByRole("button", { name: /add selected/i }));

    expect(onApply).toHaveBeenCalledWith({
      keywords: ["Rust"],
      titles: ["Staff Engineer"],
      roleAnchors: [],
      excludeTerms: [],
    });
  });

  it("disables duplicate suggestions", async () => {
    state.result = {
      state: "done",
      error: null,
      result: {
        prompt: "x",
        suggestions: [
          { value: "python", kind: "keyword", reason: "dup", status: "duplicate" },
        ],
      },
    };
    render(<SuggestSearchTermsDialog onApply={vi.fn()} />);
    await userEvent.click(
      screen.getByRole("button", { name: /suggest search terms/i }),
    );
    expect(
      await screen.findByRole("checkbox", { name: /select python/i }),
    ).toHaveAttribute("aria-disabled", "true");
  });
});
