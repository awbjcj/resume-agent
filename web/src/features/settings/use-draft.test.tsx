import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDraft } from "./use-draft";

describe("useDraft", () => {
  it("seeds the draft from data once it arrives", () => {
    const { result, rerender } = renderHook(({ data }) => useDraft(data), {
      initialProps: { data: undefined as { n: number } | undefined },
    });
    expect(result.current.draft).toBeNull();

    rerender({ data: { n: 1 } });
    expect(result.current.draft).toEqual({ n: 1 });
  });

  it("reports dirty only after the draft diverges from data", () => {
    const { result, rerender } = renderHook(({ data }) => useDraft(data), {
      initialProps: { data: { n: 1 } as { n: number } | undefined },
    });
    expect(result.current.dirty).toBe(false);

    act(() => result.current.setDraft({ n: 2 }));
    rerender({ data: { n: 1 } });
    expect(result.current.dirty).toBe(true);
  });

  it("does not clobber local edits when data is refetched unchanged", () => {
    const { result, rerender } = renderHook(({ data }) => useDraft(data), {
      initialProps: { data: { n: 1 } as { n: number } | undefined },
    });
    act(() => result.current.setDraft({ n: 99 }));
    rerender({ data: { n: 1 } }); // same reference-equal-by-value refetch
    expect(result.current.draft).toEqual({ n: 99 });
  });

  it("reset() reverts the draft back to the latest data", () => {
    const { result, rerender } = renderHook(({ data }) => useDraft(data), {
      initialProps: { data: { n: 1 } as { n: number } | undefined },
    });
    act(() => result.current.setDraft({ n: 99 }));
    rerender({ data: { n: 1 } });
    act(() => result.current.reset());
    expect(result.current.draft).toEqual({ n: 1 });
    expect(result.current.dirty).toBe(false);
  });
});
