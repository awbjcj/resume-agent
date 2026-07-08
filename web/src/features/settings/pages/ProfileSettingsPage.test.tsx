import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/test/utils";
import { ProfileSettingsPage } from "./ProfileSettingsPage";

const mocks = vi.hoisted(() => ({
  launch: vi.fn(),
}));

vi.mock("@/features/profile-sources/BuildReportPanel", () => ({
  BuildReportPanel: () => <div data-testid="build-report" />,
}));

vi.mock("@/features/profile-sources/SourceManager", () => ({
  SourceManager: () => <div data-testid="source-manager" />,
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
    data: { githubUsername: null },
  }),
  useSaveConfig: () => ({
    isPending: false,
    mutate: vi.fn(),
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
        ["setup-status", "profile-sources", "profile-skeleton"],
      ),
    );
  });
});
