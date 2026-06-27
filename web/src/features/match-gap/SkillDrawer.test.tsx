import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkillDrawer } from "./SkillDrawer";

describe("SkillDrawer", () => {
  it("shows the display label and jobs demanding the selected target", () => {
    render(
      <SkillDrawer
        kind="theme"
        targetKey="infra"
        label="Cloud / Infrastructure"
        jobs={[
          { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
          { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
        ]}
        onClose={() => {}}
      />,
    );

    expect(screen.getByRole("heading", { name: "Cloud / Infrastructure" })).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText(/Platform/)).toBeInTheDocument();
  });

  it("renders an explicit empty state for filtered targets", () => {
    render(
      <SkillDrawer
        kind="skill"
        targetKey="Kubernetes"
        label="Kubernetes"
        jobs={[]}
        onClose={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/no target jobs match/i);
  });
});
