import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { targetId, UNTHEMED_ID, type ThemeRow } from "./aggregate";
import { RankedList } from "./RankedList";

const themes: ThemeRow[] = [
  {
    id: "backend",
    label: "Backend",
    score: 12,
    jobCount: 3,
    skillCount: 2,
    gapCount: 1,
    skills: [
      {
        key: "python",
        skill: "Python",
        themeId: "backend",
        covered: false,
        score: 9,
        jobCount: 3,
        must: 3,
        nice: 0,
        tech: 0,
        members: { Python: 3 },
      },
      {
        key: "django",
        skill: "Django",
        themeId: "backend",
        covered: true,
        score: 3,
        jobCount: 1,
        must: 1,
        nice: 0,
        tech: 0,
        members: { Django: 1 },
      },
    ],
  },
];

it("discloses skills with independent selection and detail controls", async () => {
  const onToggleSelect = vi.fn();
  const onOpenSkill = vi.fn();
  render(
    <RankedList
      themeRows={themes}
      stateOf={(_kind, key) => (key === "django" ? "ready" : "none")}
      selected={new Set([targetId({ kind: "skill", key: "python" })])}
      onToggleSelect={onToggleSelect}
      onOpenSkill={onOpenSkill}
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: /expand backend/i }));
  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /select python/i })).toBeChecked();

  await userEvent.click(screen.getByRole("button", { name: /open python details/i }));
  expect(onOpenSkill).toHaveBeenCalledWith(expect.objectContaining({ key: "python" }));

  await userEvent.click(screen.getByRole("checkbox", { name: /select django/i }));
  expect(onToggleSelect).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "skill", key: "django" }),
  );
});

it("does not allow selecting the synthetic unthemed group", () => {
  render(
    <RankedList
      themeRows={[{ ...themes[0], id: UNTHEMED_ID, label: "Unthemed" }]}
      stateOf={() => "none"}
      selected={new Set()}
      onToggleSelect={vi.fn()}
      onOpenSkill={vi.fn()}
    />,
  );

  expect(screen.getByRole("checkbox", { name: "Select Unthemed theme" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
