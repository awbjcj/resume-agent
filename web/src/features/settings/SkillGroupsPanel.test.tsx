import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  value: {} as Record<string, unknown>,
  suppressed: [] as Array<Record<string, unknown>>,
  refetch: vi.fn(),
  setGroup: vi.fn(),
  clearGroup: vi.fn(),
  deleteSkill: vi.fn(),
  restoreSkill: vi.fn(),
}));

vi.mock("./use-matrix", () => ({
  useMatrix: () => ({ ...state.value, refetch: state.refetch }),
  useSetSkillGroup: () => ({ mutate: state.setGroup, isPending: false }),
  useClearSkillGroup: () => ({ mutate: state.clearGroup, isPending: false }),
  useDeleteSkill: () => ({ mutate: state.deleteSkill, isPending: false }),
  useRestoreSkill: () => ({ mutate: state.restoreSkill, isPending: false }),
  useSuppressedSkills: () => ({ data: state.suppressed }),
}));

import { SkillGroupsPanel } from "./SkillGroupsPanel";

const groups = [
  { slug: "languages", label: "Languages" },
  { slug: "other", label: "Other" },
];

describe("SkillGroupsPanel", () => {
  beforeEach(() => {
    state.refetch.mockReset();
    state.setGroup.mockReset();
    state.clearGroup.mockReset();
    state.deleteSkill.mockReset();
    state.restoreSkill.mockReset();
    state.suppressed = [];
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

  it("moves a skill to another group and resets a pinned one", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-16T00:00:00Z",
        groups,
        rows: [
          {
            key: "python",
            display: "Python",
            category: "hard",
            group: "languages",
            groupSource: "taxonomy",
            inferred: false,
            strength: 3,
            lastUsed: "current",
          },
          {
            key: "dbt",
            display: "dbt",
            category: "hard",
            group: "languages",
            groupSource: "correction",
            inferred: false,
            strength: 1,
            lastUsed: null,
          },
        ],
      },
    };
    render(<SkillGroupsPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: /change group for python/i }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: /^other$/i }));
    expect(state.setGroup).toHaveBeenCalledWith({ key: "python", group: "other" });

    const pinnedTrigger = screen.getByRole("button", {
      name: /change group for dbt/i,
    });
    expect(pinnedTrigger.querySelector('[data-icon="inline-start"]')).not.toBeNull();
    await userEvent.click(pinnedTrigger);
    await userEvent.click(
      await screen.findByRole("menuitem", { name: /reset to automatic/i }),
    );
    expect(state.clearGroup).toHaveBeenCalledWith("dbt");
  });

  it("does not offer reset for an automatic assignment", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-16T00:00:00Z",
        groups,
        rows: [
          {
            key: "python",
            display: "Python",
            category: "hard",
            group: "languages",
            groupSource: "taxonomy",
            inferred: false,
            strength: 3,
            lastUsed: "current",
          },
        ],
      },
    };
    render(<SkillGroupsPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: /change group for python/i }),
    );

    expect(await screen.findByRole("menuitem", { name: /^other$/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /reset to automatic/i })).toBeNull();
  });

  it("deletes a skill via the row menu", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-20T00:00:00Z",
        groups,
        rows: [
          {
            key: "kubernetes",
            display: "Kubernetes",
            category: "hard",
            group: "languages",
            groupSource: "taxonomy",
            inferred: false,
            strength: 2,
            lastUsed: null,
          },
        ],
      },
    };
    render(<SkillGroupsPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: /change group for kubernetes/i }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete skill/i }));
    expect(state.deleteSkill).toHaveBeenCalledWith("kubernetes");
  });

  it("restores a suppressed skill", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: { generatedAt: "", groups, rows: [
        { key: "python", display: "Python", category: "hard", group: "languages",
          groupSource: "taxonomy", inferred: false, strength: 3, lastUsed: null },
      ] },
    };
    state.suppressed = [
      { token: "kubernetes", display: "Kubernetes", addedAt: "" },
    ];
    render(<SkillGroupsPanel />);

    expect(screen.getByText(/deleted skills/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /restore kubernetes/i }));
    expect(state.restoreSkill).toHaveBeenCalledWith("kubernetes");
  });
});
