import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCooldown } from "./useCooldown";

afterEach(() => vi.useRealTimers());

describe("useCooldown", () => {
  it("counts real elapsed seconds down to zero", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useCooldown(2));
    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.seconds).toBe(1);
    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.seconds).toBe(0);
  });
});
