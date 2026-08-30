import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { changeLanguage } from "@/i18n";
import { withQueryClient } from "@/test/utils";
import { ReviewSettingsPage } from "./ReviewSettingsPage";

const save = vi.fn();

const LENGTH_BUDGET = {
  pageTarget: 2,
  maxExperiences: 5,
  maxProjects: 4,
  maxEvidenceOwners: 8,
  minBulletsPerRole: 5,
  maxBulletsPerRole: 7,
  minBulletsPerProject: 4,
  maxBulletsPerProject: 6,
  targetTotalBullets: 40,
  minAspectsPerOwner: 3,
  targetSkills: 40,
  maxSkillsPerCategory: 12,
};

const REVIEWERS = [
  { name: "fact-check", gate: true, weight: 0, modelTier: "premium", scoreBands: false },
  { name: "ats-keyword", gate: false, weight: 1, modelTier: "mid", scoreBands: true },
];

vi.mock("../use-config", () => ({
  useConfig: () => ({
    data: {
      maxRounds: 3,
      scoreThreshold: 85,
      mergedAdvisory: false,
      evidencePortfolioEnabled: false,
      earlyStopOnRegression: false,
      tailorTier: "premium",
      reviserTier: "premium",
      provenanceRetryBudget: 1,
      styleGuidePath: "config/style_guide.md",
      reviewers: REVIEWERS,
      lengthBudget: LENGTH_BUDGET,
    },
  }),
  useSaveConfig: (path: string) => ({
    mutate: (body: unknown) => save(path, body),
    isPending: false,
  }),
}));

beforeEach(() => save.mockClear());

const saveChanges = () =>
  userEvent.click(screen.getByRole("button", { name: "Save changes" }));

describe("ReviewSettingsPage pipeline controls", () => {
  it("saves merged advisory and writer tier changes", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("switch", { name: /merge advisory/i }));
    await userEvent.click(screen.getByRole("button", { name: "Standard Writer model tier" }));
    await userEvent.click(screen.getByRole("button", { name: "Economy Reviser model tier" }));
    await saveChanges();
    expect(save).toHaveBeenCalledWith(
      "/api/config/review",
      expect.objectContaining({
        mergedAdvisory: true,
        tailorTier: "mid",
        reviserTier: "cheap",
      }),
    );
  });

  it("localizes model tiers while keeping their saved values canonical", async () => {
    await changeLanguage("zh-CN");
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });

    expect(screen.getByText("硬性门槛")).toBeInTheDocument();
    expect(screen.getByText(/启用硬性门槛的评审会直接阻断本轮/)).toBeInTheDocument();
    expect(screen.getByText(/阻断项/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "写作模型档位：标准型" }));
    await userEvent.click(screen.getByRole("button", { name: "保存更改" }));

    expect(save).toHaveBeenCalledWith(
      "/api/config/review",
      expect.objectContaining({ tailorTier: "mid" }),
    );
  });

  it("switches to the deep roster and saves against its own endpoint", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("button", { name: "Deep roster" }));
    await userEvent.click(screen.getByRole("switch", { name: /merge advisory/i }));
    await saveChanges();
    expect(save).toHaveBeenCalledWith(
      "/api/config/review-deep",
      expect.objectContaining({ mergedAdvisory: true }),
    );
  });
});

describe("ReviewSettingsPage resume shape", () => {
  it("edits the skills budget, which had no control at all before", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    const target = screen.getByLabelText("Target skills");
    await userEvent.clear(target);
    await userEvent.type(target, "60");
    await saveChanges();
    expect(save).toHaveBeenCalledWith(
      "/api/config/review",
      expect.objectContaining({
        lengthBudget: expect.objectContaining({ targetSkills: 60 }),
      }),
    );
  });

  it("edits the per-entry depth floors", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    const aspects = screen.getByLabelText("Min aspects per entry");
    await userEvent.clear(aspects);
    await userEvent.type(aspects, "4");
    await saveChanges();
    expect(save).toHaveBeenCalledWith(
      "/api/config/review",
      expect.objectContaining({
        lengthBudget: expect.objectContaining({ minAspectsPerOwner: 4 }),
      }),
    );
  });

  it("blocks saving an inverted bullet range instead of letting the server 422", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    const min = screen.getByLabelText("Min bullets per role");
    await userEvent.clear(min);
    await userEvent.type(min, "9"); // max is 7
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(screen.getAllByText(/cannot exceed the maximum/i).length).toBeGreaterThan(0);
  });

  it("exposes the advanced knobs that previously only existed in YAML", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("button", { name: /advanced/i }));
    await userEvent.click(
      screen.getByRole("switch", { name: /stop early on regression/i }),
    );
    await saveChanges();
    expect(save).toHaveBeenCalledWith(
      "/api/config/review",
      expect.objectContaining({ earlyStopOnRegression: true }),
    );
  });
});

describe("ReviewSettingsPage reviewer roster", () => {
  it("disables weight and score bands for a gated reviewer", () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    // fact-check ships gated: its weight is never read by the scorer.
    expect(screen.getByLabelText("fact-check weight")).toBeDisabled();
    expect(screen.getByRole("switch", { name: "fact-check score bands" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    // An ungated reviewer keeps both.
    expect(screen.getByLabelText("ats-keyword weight")).not.toBeDisabled();
  });

  it("re-enables weight when the gate is turned off, preserving its value", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("switch", { name: "fact-check gate" }));
    const weight = screen.getByLabelText("fact-check weight");
    expect(weight).not.toBeDisabled();
    expect(weight).toHaveValue(0);
  });

  it("edits score bands, which round-tripped but was never editable", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(
      screen.getByRole("switch", { name: "ats-keyword score bands" }),
    );
    await saveChanges();
    const [, body] = save.mock.calls.at(-1)!;
    expect((body as { reviewers: { name: string; scoreBands: boolean }[] }).reviewers)
      .toContainEqual(expect.objectContaining({ name: "ats-keyword", scoreBands: false }));
  });
});

describe("ReviewSettingsPage roster switching", () => {
  it("asks before discarding unsaved edits", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("switch", { name: /merge advisory/i }));

    await userEvent.click(screen.getByRole("button", { name: "Deep roster" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/discard unsaved changes/i)).toBeInTheDocument();

    // Backing out keeps the edit and stays on Fast.
    await userEvent.click(within(dialog).getByRole("button", { name: /keep editing/i }));
    expect(screen.getByRole("switch", { name: /merge advisory/i })).toBeChecked();
    await saveChanges();
    expect(save).toHaveBeenCalledWith("/api/config/review", expect.anything());
  });

  it("switches without prompting when nothing is dirty", async () => {
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    await userEvent.click(screen.getByRole("button", { name: "Deep roster" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows the selected roster's description and hides the other", async () => {
    // Both descriptions stay in the DOM so the grid cell keeps the height of
    // the longest one — switching must not shift the page. The inactive one is
    // hidden from assistive tech rather than removed.
    render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    const fast = screen.getByText(/used by default when tailoring/i);
    const deep = screen.getByText(/a separate roster, saved separately/i);

    expect(fast).not.toHaveAttribute("aria-hidden", "true");
    expect(deep).toHaveAttribute("aria-hidden", "true");

    await userEvent.click(screen.getByRole("button", { name: "Deep roster" }));
    expect(deep).not.toHaveAttribute("aria-hidden", "true");
    expect(fast).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps the roster switch out of a horizontal Field", () => {
    // This is the alignment defect, encoded. The switch used to live in a
    // `Field orientation="horizontal"` whose label+toggle sat in a plain div
    // rather than FieldContent, so `has-[>[data-slot=field-content]]:items-start`
    // never fired and the description stayed vertically centred against a
    // two-row stack. Fast/Deep is the page's scope, not one of its settings, so
    // the fix was to stop rendering it as a field at all.
    const { container } = render(<ReviewSettingsPage />, { wrapper: withQueryClient });
    const roster = screen.getByRole("group", { name: "Roster" });
    expect(roster.closest('[data-slot="field"]')).toBeNull();
    expect(
      container.querySelectorAll('[data-orientation="horizontal"] [data-slot="toggle-group"]'),
    ).toHaveLength(0);
  });
});
