import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  value: {} as Record<string, unknown>,
  refetch: vi.fn(),
}));

vi.mock("./use-matrix", () => ({
  useMatrix: () => ({ ...state.value, refetch: state.refetch }),
}));

import { SkillGroupsPanel } from "./SkillGroupsPanel";

const groups = [
  { slug: "languages", label: "Languages" },
  { slug: "other", label: "Other" },
];

describe("SkillGroupsPanel", () => {
  beforeEach(() => {
    state.refetch.mockReset();
  });

  it("renders explicit loading, error/retry, and empty states", async () => {
    state.value = { isPending: true, isError: false };
    const loading = render(<SkillGroupsPanel />);
    expect(screen.getByLabelText(/loading skill matrix/i)).toBeInTheDocument();
    loading.unmount();

    state.value = { isPending: false, isError: true, error: new Error("offline") };
    const failed = render(<SkillGroupsPanel />);
    expect(screen.getByText(/couldn't load the skill matrix/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(state.refetch).toHaveBeenCalledTimes(1);
    failed.unmount();

    state.value = {
      isPending: false,
      isError: false,
      data: { generatedAt: "", groups, rows: [] },
    };
    render(<SkillGroupsPanel />);
    expect(screen.getByText(/run a profile build/i)).toBeInTheDocument();
  });

  it("uses server vocabulary order, buckets nulls into Other, and shows counts", () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-10T00:00:00Z",
        groups,
        rows: [
          { key: "python", display: "Python", category: "hard", group: "languages",
            inferred: false, strength: 3, lastUsed: "current" },
          { key: "mystery", display: "Mystery", category: null, group: null,
            inferred: true, strength: 0.5, lastUsed: null },
        ],
      },
    };
    render(<SkillGroupsPanel />);
    const triggers = screen.getAllByRole("button", { name: /languages|other/i });
    expect(triggers[0]).toHaveTextContent("Languages");
    expect(triggers[1]).toHaveTextContent("Other");
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Mystery")).toBeInTheDocument();
    expect(triggers[0]).toHaveTextContent("1");
    expect(triggers[1]).toHaveTextContent("1");
  });
});
