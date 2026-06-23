import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
    );
    expect(screen.getByText("Nice-to-have")).toBeInTheDocument();
    expect(screen.queryByText("Best-have")).not.toBeInTheDocument();
  });
});
