import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/test/utils";
import { ProfileWorkspace } from "./ProfileWorkspace";

const mocks = vi.hoisted(() => ({
  launch: vi.fn(),
  save: vi.fn(),
}));

vi.mock("@/features/profile-sources/BuildReportPanel", () => ({
  BuildReportPanel: () => <div data-testid="build-report" />,
}));

vi.mock("@/features/profile-sources/SourceManager", () => ({
  SourceManager: () => <div data-testid="source-manager" />,
}));

vi.mock("@/features/coach/use-coach", () => ({
  useCoachSessions: () => ({ data: { sessions: [] } }),
}));

vi.mock("@/features/settings/SkillGroupsPanel", () => ({
  SkillGroupsPanel: () => <div data-testid="skill-groups" />,
}));

vi.mock("@/features/runs/use-active-run", () => ({
  useActiveRun: () => null,
}));

vi.mock("@/features/runs/use-launch-run", () => ({
  launchers: { profileBuild: vi.fn() },
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

vi.mock("@/features/settings/use-config", () => ({
  useConfig: () => ({
    data: {
      githubUsername: null,
      githubRepoAllow: [],
      githubRepoDeny: [],
      githubRepoLimit: 20,
    },
  }),
  useSaveConfig: () => ({ isPending: false, mutate: mocks.save }),
}));

vi.mock("@/features/settings/use-setup-status", () => ({
  useSetupStatus: () => ({ data: { profile: { factsBuiltAt: null } } }),
}));

describe("ProfileWorkspace", () => {
  it("keeps the coach hero visible and refreshes queries after a profile rebuild", async () => {
    const user = userEvent.setup();
    render(<ProfileWorkspace />, { wrapper: withQueryClient });

    // coach is a persistent hero action, not tucked in a tab
    expect(screen.getByRole("link", { name: /open coach/i })).toHaveAttribute("href", "/coach");

    await user.click(screen.getByRole("button", { name: /rebuild profile/i }));

    await waitFor(() =>
      expect(mocks.launch).toHaveBeenCalledWith(
        "profile-build",
        expect.any(Function),
        ["setup-status", "profile-sources", "profile-skeleton", "profile-matrix"],
      ),
    );
  });

  it("edits repo harvest controls on Documents and mounts grouped skills on Skills", async () => {
    const user = userEvent.setup();
    render(<ProfileWorkspace />, { wrapper: withQueryClient });

    // Documents tab is active by default
    await user.type(screen.getByLabelText(/always include repositories/i), "important, fork");
    await user.type(screen.getByLabelText(/exclude repositories/i), "noise");
    await user.clear(screen.getByLabelText(/repository limit/i));
    await user.type(screen.getByLabelText(/repository limit/i), "5");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({
        githubRepoAllow: ["important", "fork"],
        githubRepoDeny: ["noise"],
        githubRepoLimit: 5,
      }),
    );

    // Skills live behind their own tab — no longer stacked on one page
    expect(screen.queryByTestId("skill-groups")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /skills/i }));
    expect(await screen.findByTestId("skill-groups")).toBeInTheDocument();
  });
});
