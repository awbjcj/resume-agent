import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSelection } from "./use-selection";

describe("useSelection", () => {
  it("toggles ids and escalates to query mode", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.selectPage([1, 2, 3]));
    expect(result.current.count).toBe(3);
    expect(result.current.mode).toBe("ids");
    act(() => result.current.selectAllMatching(4210));
    expect(result.current.mode).toBe("query");
    expect(result.current.isAllMatching).toBe(true);
    expect(result.current.count).toBe(4210);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
    expect(result.current.mode).toBe("ids");
  });

  it("prunes id mode and refreshes query count after a filter change", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.selectPage([1, 2, 3]));
    act(() => result.current.reconcile([2, 3], 2));
    expect([...result.current.ids]).toEqual([2, 3]);
    act(() => result.current.selectAllMatching(4210));
    act(() => result.current.reconcile([2], 9));
    expect(result.current.count).toBe(9);
    expect(result.current.mode).toBe("query");
  });

  it("downgrades query selection to visible ids when a row is toggled", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.selectAllMatching(4210));
    expect(result.current.isSelected(2)).toBe(true);
    act(() => result.current.toggle(2, 1, false, [1, 2, 3]));
    expect(result.current.mode).toBe("ids");
    expect(result.current.count).toBe(2);
    expect([...result.current.ids]).toEqual([1, 3]);
  });
});
