import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useArtifactSelection } from "./use-artifact-selection";

describe("useArtifactSelection", () => {
  it("toggles ids on and off", () => {
    const { result } = renderHook(() => useArtifactSelection([1, 2, 3]));

    act(() => result.current.toggle(2));
    expect(result.current.selectedIds).toEqual([2]);

    act(() => result.current.toggle(2));
    expect(result.current.selectedIds).toEqual([]);
  });

  it("reports ids in list order, not click order", () => {
    // The bulk-delete request should read the way the list looks.
    const { result } = renderHook(() => useArtifactSelection([1, 2, 3]));

    act(() => result.current.toggle(3));
    act(() => result.current.toggle(1));

    expect(result.current.selectedIds).toEqual([1, 3]);
  });

  it("drops a selected id once it stops being deletable", () => {
    // The real path: the user checks a version, then marks it Applied. Its
    // checkbox goes disabled, but a selection that survived would be submitted
    // to a bulk delete the API refuses for the entire batch.
    const { result, rerender } = renderHook(
      ({ ids }) => useArtifactSelection(ids),
      { initialProps: { ids: [1, 2] } },
    );

    act(() => result.current.toggle(1));
    expect(result.current.selectedIds).toEqual([1]);

    rerender({ ids: [2] });
    expect(result.current.selectedIds).toEqual([]);
  });

  it("select-all covers only deletable ids, and toggles back off", () => {
    const { result } = renderHook(() => useArtifactSelection([4, 5]));

    act(() => result.current.toggleAll());
    expect(result.current.selectedIds).toEqual([4, 5]);
    expect(result.current.allSelected).toBe(true);

    act(() => result.current.toggleAll());
    expect(result.current.selectedIds).toEqual([]);
  });

  it("is not 'all selected' when there is nothing to select", () => {
    const { result } = renderHook(() => useArtifactSelection([]));

    expect(result.current.allSelected).toBe(false);
  });

  it("clears the selection after a delete succeeds", () => {
    const { result } = renderHook(() => useArtifactSelection([7, 8]));

    act(() => result.current.toggleAll());
    act(() => result.current.clear());

    expect(result.current.selectedIds).toEqual([]);
  });
});
