import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { UNASSIGNED_ID, type DomainRow } from "./aggregate";
import { SkillMap } from "./SkillMap";

const domainRows: DomainRow[] = [
  {
    id: "backend",
    label: "Backend",
    category: "engineering",
    score: 16,
    jobCount: 3,
    skillCount: 1,
    gapCount: 1,
    adjacentCount: 0,
    skills: [
      {
        key: "python",
        skill: "Python",
        domainId: "backend",
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
const categoryRows = [{ slug: "engineering", label: "Engineering", kind: "hard" as const, score: 16, jobCount: 3, skillCount: 1, gapCount: 1, adjacentCount: 0, domains: domainRows }];
const categories = [{ slug: "engineering", label: "Engineering", kind: "hard" as const }];

it("focuses a domain and exposes real skill controls", async () => {
  const onToggleSelect = vi.fn();
  const onOpenSkill = vi.fn();
  render(
    <SkillMap
      categoryRows={categoryRows}
      categories={categories}
      stateOf={(kind) => (kind === "skill" ? "ready" : "none")}
      selected={new Set()}
      onToggleSelect={onToggleSelect}
      onOpenSkill={onOpenSkill}
    />,
  );

  expect(screen.queryByRole("checkbox", { name: /select engineering/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /explore engineering/i }));
  await userEvent.click(screen.getByRole("button", { name: /explore backend/i }));
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

it("does not allow selecting the synthetic undomaind map node", async () => {
  render(
    <SkillMap
      categoryRows={[{ ...categoryRows[0], domains: [{ ...domainRows[0], id: UNASSIGNED_ID, label: "Unassigned" }] }]}
      categories={categories}
      stateOf={() => "none"}
      selected={new Set()}
      onToggleSelect={vi.fn()}
      onOpenSkill={vi.fn()}
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: /explore engineering/i }));
  expect(screen.getByRole("checkbox", { name: "Select Unassigned" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
