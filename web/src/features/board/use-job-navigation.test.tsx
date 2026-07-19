import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useJobNavigation, type JobNavPagination } from "./use-job-navigation";

describe("useJobNavigation", () => {
  it("disables prev at the first item and next at the last (no pagination)", () => {
    const nav = vi.fn();
    const first = renderHook(() => useJobNavigation([1, 2, 3], 1, nav));
    expect(first.result.current.hasPrev).toBe(false);
    expect(first.result.current.hasNext).toBe(true);

    const last = renderHook(() => useJobNavigation([1, 2, 3], 3, nav));
    expect(last.result.current.hasPrev).toBe(true);
    expect(last.result.current.hasNext).toBe(false);
  });

  it("steps to the neighbouring id on goPrev/goNext", () => {
    const nav = vi.fn();
    const { result } = renderHook(() => useJobNavigation([10, 20, 30], 20, nav));
    act(() => result.current.goPrev());
    expect(nav).toHaveBeenCalledWith(10);
    act(() => result.current.goNext());
    expect(nav).toHaveBeenCalledWith(30);
  });

  it("is inert when the current id is not in the list", () => {
    const nav = vi.fn();
    const { result } = renderHook(() => useJobNavigation([1, 2], 99, nav));
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(false);
    act(() => result.current.goNext());
    act(() => result.current.goPrev());
    expect(nav).not.toHaveBeenCalled();
  });

  it("keeps hasNext true at the loaded edge while more pages exist", () => {
    const nav = vi.fn();
    const pagination: JobNavPagination = {
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
    };
    const { result } = renderHook(() =>
      useJobNavigation([1, 2], 2, nav, pagination),
    );
    expect(result.current.hasNext).toBe(true);
  });

  it("auto-fetches the next page, then advances once rows land", () => {
    const nav = vi.fn();
    const fetchNextPage = vi.fn();
    const pagination: JobNavPagination = {
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage,
    };
    const { result, rerender } = renderHook(
      ({ ids }: { ids: number[] }) => useJobNavigation(ids, 2, nav, pagination),
      { initialProps: { ids: [1, 2] } },
    );

    // At the loaded edge: goNext requests the next page instead of navigating.
    act(() => result.current.goNext());
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
    expect(nav).not.toHaveBeenCalled();
    expect(result.current.isLoadingNext).toBe(true);

    // Rapid re-press while pending must not fire a second fetch.
    act(() => result.current.goNext());
    expect(fetchNextPage).toHaveBeenCalledTimes(1);

    // New page lands -> hook advances to the first new row and clears loading.
    rerender({ ids: [1, 2, 3] });
    expect(nav).toHaveBeenCalledWith(3);
    expect(result.current.isLoadingNext).toBe(false);
  });

  it("clears a pending advance if the modal closes before the page lands, instead of firing later", () => {
    const nav = vi.fn();
    const fetchNextPage = vi.fn();
    const pagination: JobNavPagination = {
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage,
    };
    const { result, rerender } = renderHook(
      ({ ids, currentId }: { ids: number[]; currentId: number | null }) =>
        useJobNavigation(ids, currentId, nav, pagination),
      { initialProps: { ids: [1, 2], currentId: 2 as number | null } },
    );

    // At the loaded edge: request the next page.
    act(() => result.current.goNext());
    expect(result.current.isLoadingNext).toBe(true);

    // The modal closes before the page arrives.
    rerender({ ids: [1, 2], currentId: null });

    // The page lands while nothing is open: the stale request must not
    // linger, and nothing should navigate since no job is open.
    rerender({ ids: [1, 2, 3], currentId: null });
    expect(nav).not.toHaveBeenCalled();
    expect(result.current.isLoadingNext).toBe(false);

    // Opening an earlier job afterwards must not auto-jump forward because
    // of the abandoned request.
    rerender({ ids: [1, 2, 3], currentId: 1 });
    expect(nav).not.toHaveBeenCalled();
  });
});
