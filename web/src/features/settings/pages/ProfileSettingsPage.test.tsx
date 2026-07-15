import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/test/utils";
import { ProfileSettingsPage } from "./ProfileSettingsPage";

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

vi.mock("@/features/interview/InterviewPanel", () => ({
  InterviewPanel: () => <div data-testid="interview-panel" />,
}));

vi.mock("../SkillGroupsPanel", () => ({
  SkillGroupsPanel: () => <div data-testid="skill-groups" />,
}));

vi.mock("@/features/runs/use-active-run", () => ({
  useActiveRun: () => null,
}));

vi.mock("@/features/runs/use-launch-run", () => ({
  launchers: {
    profileBuild: vi.fn(),
  },
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

vi.mock("../use-config", () => ({
  useConfig: () => ({
    data: {
      githubUsername: null,
      githubRepoAllow: [],
      githubRepoDeny: [],
      githubRepoLimit: 20,
    },
  }),
  useSaveConfig: () => ({
    isPending: false,
    mutate: mocks.save,
  }),
}));

vi.mock("../use-setup-status", () => ({
  useSetupStatus: () => ({
    data: { profile: { factsBuiltAt: null } },
  }),
}));

describe("ProfileSettingsPage", () => {
  it("refreshes source and skeleton queries after a profile rebuild", async () => {
    const user = userEvent.setup();
    render(<ProfileSettingsPage />, { wrapper: withQueryClient });

    await user.click(screen.getByRole("button", { name: /rebuild profile/i }));

    await waitFor(() =>
      expect(mocks.launch).toHaveBeenCalledWith(
        "profile-build",
        expect.any(Function),
        ["setup-status", "profile-sources", "profile-skeleton", "profile-matrix"],
      ),
    );
  });

  it("edits all repo harvest controls and mounts grouped skills", async () => {
    const user = userEvent.setup();
    render(<ProfileSettingsPage />, { wrapper: withQueryClient });
    expect(screen.getByTestId("skill-groups")).toBeInTheDocument();
    expect(screen.getByTestId("interview-panel")).toBeInTheDocument();

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
  });
});
