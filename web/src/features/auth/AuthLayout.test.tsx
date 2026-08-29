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
    expect(screen.getByText("Secure workspace")).toBeInTheDocument();
  });
});
