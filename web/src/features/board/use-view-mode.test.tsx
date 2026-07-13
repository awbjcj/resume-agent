import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useViewMode } from "./use-view-mode";

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter initialEntries={["/?job=7"]}>{children}</MemoryRouter>;
}

describe("useViewMode", () => {
  beforeEach(() => localStorage.clear());

  it("persists list view and preserves unrelated URL parameters", () => {
    const { result } = renderHook(
      () => ({ view: useViewMode("test-view"), location: useLocation() }),
      { wrapper },
    );
    act(() => result.current.view[1]("list"));
    expect(result.current.view[0]).toBe("list");
    expect(localStorage.getItem("test-view")).toBe("list");
    expect(result.current.location.search).toContain("job=7");
    expect(result.current.location.search).toContain("view=list");
  });
});
