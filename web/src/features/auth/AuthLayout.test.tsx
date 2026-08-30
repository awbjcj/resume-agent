import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthLayout } from "./AuthLayout";

describe("AuthLayout", () => {
  it("renders one main landmark and keeps the generated brand art decorative", () => {
    const { container } = render(
      <AuthLayout title="Sign in" description="Welcome back">
        <p>Form</p>
      </AuthLayout>,
    );
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(container.querySelector("[data-slot='auth-brand']")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(
      container.querySelector("[data-slot='auth-brand'] img")?.getAttribute("src"),
    ).toContain("auth-evidence-command-center");
    const visual = container.querySelector("[data-slot='auth-brand-visual']");
    const copy = container.querySelector("[data-slot='auth-brand-copy']");
    expect(visual).toBeInTheDocument();
    expect(copy).toBeInTheDocument();
    expect(visual?.nextElementSibling).toBe(copy);
    expect(visual?.querySelector("img")).toHaveClass("object-contain");
    expect(copy?.querySelector("img")).toBeNull();
    expect(screen.getByText("Secure workspace")).toBeInTheDocument();
  });
});
