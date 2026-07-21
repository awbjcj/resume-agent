import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { withQueryClient } from "@/test/utils";
import { SkillMatrix } from "./SkillMatrix";

describe("SkillMatrix", () => {
  it("labels the optional group 'Nice-to-have'", () => {
    render(
      <SkillMatrix
        skills={[
          { name: "Python", required: true, covered: true },
          { name: "Go", required: false, covered: false },
        ]}
      />,
      { wrapper: withQueryClient },
    );
    expect(screen.getByText("Nice-to-have")).toBeInTheDocument();
    expect(screen.queryByText("Best-have")).not.toBeInTheDocument();
  });

  it("renders covered and gap chips sharing the skill-chip class", () => {
    const { container } = render(
      <SkillMatrix
        skills={[
          { name: "Python", required: true, covered: true },
          { name: "Rust", required: true, covered: false },
        ]}
      />,
      { wrapper: withQueryClient },
    );
    expect(container.querySelectorAll(".skill-chip").length).toBe(2);
  });

  it("wraps the gap chip's add affordance in a size-constrained inline box", () => {
    const { container } = render(
      <SkillMatrix
        skills={[
          { name: "Python", required: true, covered: true },
          { name: "Rust", required: true, covered: false },
        ]}
      />,
      { wrapper: withQueryClient },
    );
    const gapChip = Array.from(container.querySelectorAll(".skill-chip")).find(
      (chip) => chip.getAttribute("data-covered") === "false",
    );
    const coveredChip = Array.from(container.querySelectorAll(".skill-chip")).find(
      (chip) => chip.getAttribute("data-covered") === "true",
    );
    expect(screen.getByRole("button", { name: /add "rust"/i })).toBeInTheDocument();
    // The affordance sits inside a fixed size-4 box so it can't stretch the chip.
    expect(gapChip?.querySelector(".size-4")).not.toBeNull();
    expect(coveredChip?.querySelector("button")).toBeNull();
  });
});
