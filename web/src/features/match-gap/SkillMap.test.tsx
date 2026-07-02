import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { UNTHEMED_ID, type ThemeRow } from "./aggregate";
import { SkillMap } from "./SkillMap";

const themeRows: ThemeRow[] = [
  {
    id: "backend",
    label: "Backend",
    score: 16,
    jobCount: 3,
    skillCount: 1,
    gapCount: 1,
    adjacentCount: 0,
    skills: [
      {
        key: "python",
        skill: "Python",
        themeId: "backend",
        covered: false,
        coverage: "gap",
        score: 9,
        jobCount: 3,
        must: 3,
        nice: 0,
        tech: 0,
        members: {},
      },
    ],
  },
];

it("focuses a theme and exposes real skill controls", async () => {
  const onToggleSelect = vi.fn();
  const onOpenSkill = vi.fn();
  render(
    <SkillMap
      themeRows={themeRows}
      stateOf={(kind) => (kind === "skill" ? "ready" : "none")}
      selected={new Set()}
      onToggleSelect={onToggleSelect}
      onOpenSkill={onOpenSkill}
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: /focus backend/i }));
  expect(screen.getByRole("button", { name: /open python details/i })).toBeInTheDocument();
  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByText("Adjacent")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("checkbox", { name: /select python/i }));
  expect(onToggleSelect).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "skill", key: "python" }),
  );

  await userEvent.click(screen.getByRole("button", { name: /open python details/i }));
  expect(onOpenSkill).toHaveBeenCalledWith(expect.objectContaining({ key: "python" }));
});

it("does not allow selecting the synthetic unthemed map node", () => {
  render(
    <SkillMap
      themeRows={[{ ...themeRows[0], id: UNTHEMED_ID, label: "Unthemed" }]}
      stateOf={() => "none"}
      selected={new Set()}
      onToggleSelect={vi.fn()}
      onOpenSkill={vi.fn()}
    />,
  );

  expect(screen.getByRole("checkbox", { name: "Select Unthemed" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
