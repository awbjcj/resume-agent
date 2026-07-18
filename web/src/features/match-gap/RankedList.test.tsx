import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { targetId, UNASSIGNED_ID, type DomainRow } from "./aggregate";
import { RankedList } from "./RankedList";

const domains: DomainRow[] = [
  {
    id: "backend",
    label: "Backend",
    category: "engineering",
    score: 12,
    jobCount: 3,
    skillCount: 2,
    gapCount: 1,
    adjacentCount: 1,
    skills: [
      {
        key: "python",
        skill: "Python",
        domainId: "backend",
        covered: false,
        coverage: "adjacent",
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
        domainId: "backend",
        covered: true,
        coverage: "covered",
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
const categoryRows = [{ slug: "engineering", label: "Engineering", kind: "hard" as const, score: 12, jobCount: 3, skillCount: 2, gapCount: 1, adjacentCount: 1, domains }];

it("discloses skills with independent selection and detail controls", async () => {
  const onToggleSelect = vi.fn();
  const onOpenSkill = vi.fn();
  render(
    <RankedList
      domainRows={domains}
      categoryRows={categoryRows}
      stateOf={(_kind, key) => (key === "django" ? "ready" : "none")}
      selected={new Set([targetId({ kind: "skill", key: "python" })])}
      onToggleSelect={onToggleSelect}
      onOpenSkill={onOpenSkill}
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: /expand backend/i }));
  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByText("Adjacent")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /select python/i })).toBeChecked();

  await userEvent.click(screen.getByRole("button", { name: /open python details/i }));
  expect(onOpenSkill).toHaveBeenCalledWith(expect.objectContaining({ key: "python" }));

  await userEvent.click(screen.getByRole("checkbox", { name: /select django/i }));
  expect(onToggleSelect).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "skill", key: "django" }),
  );
});

it("does not allow selecting the synthetic undomaind group", () => {
  render(
    <RankedList
      domainRows={[{ ...domains[0], id: UNASSIGNED_ID, label: "Unassigned" }]}
      categoryRows={[{ ...categoryRows[0], slug: "other", label: "Other", domains: [{ ...domains[0], id: UNASSIGNED_ID, label: "Unassigned", category: "other" }] }]}
      stateOf={() => "none"}
      selected={new Set()}
      onToggleSelect={vi.fn()}
      onOpenSkill={vi.fn()}
    />,
  );

  expect(screen.getByRole("checkbox", { name: "Select Unassigned domain" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
