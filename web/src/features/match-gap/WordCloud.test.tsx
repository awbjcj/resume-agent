import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SkillRow } from "./aggregate";
import { WordCloud } from "./WordCloud";

const rows: SkillRow[] = [
  {
    skill: "Kubernetes",
    themeId: "infra",
    covered: false,
    score: 9,
    jobCount: 9,
    must: 3,
    nice: 0,
    tech: 0,
  },
  {
    skill: "Python",
    themeId: "lang",
    covered: true,
    score: 2,
    jobCount: 2,
    must: 0,
    nice: 1,
    tech: 0,
  },
];

describe("WordCloud", () => {
  it("renders an accessible button per skill and selects it", async () => {
    const onSelect = vi.fn();
    render(<WordCloud skills={rows} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: /Kubernetes/ }));

    expect(onSelect).toHaveBeenCalledWith("Kubernetes");
  });

  it("exposes gap and covered status without relying on color", () => {
    render(<WordCloud skills={rows} onSelect={() => {}} />);

    expect(screen.getByRole("button", { name: /Kubernetes/ })).toHaveAttribute(
      "data-covered",
      "false",
    );
    expect(screen.getByRole("button", { name: /Kubernetes/ })).toHaveAccessibleName(/gap/);
    expect(screen.getByRole("button", { name: /Python/ })).toHaveAccessibleName(/covered/);
  });
});
