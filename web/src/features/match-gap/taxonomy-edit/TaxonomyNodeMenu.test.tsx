import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { MapNode } from "../skill-map-layout";
import { TaxonomyNodeMenu } from "./TaxonomyNodeMenu";

const base = { entityKey: "python", label: "Python", radius: 12, width: 80, height: 54, score: 1, x: 0, y: 0 };
const skill = { key: "python", skill: "Python", domainId: "backend", covered: false, coverage: "gap" as const, score: 1, jobCount: 1, must: 1, nice: 0, tech: 0, members: {} };

it("shows a skill edit menu trigger and no menu for category nodes", () => {
  const onAction = vi.fn();
  const { rerender } = render(<TaxonomyNodeMenu node={{ ...base, id: "skill:python", kind: "skill", skill } as MapNode} categoryRows={[]} onAction={onAction} />);
  expect(screen.getByRole("button", { name: "Edit Python" })).toBeInTheDocument();
  rerender(<TaxonomyNodeMenu node={{ ...base, id: "category:languages", kind: "category" } as MapNode} categoryRows={[]} onAction={onAction} />);
  expect(screen.queryByRole("button", { name: "Edit Python" })).not.toBeInTheDocument();
});
