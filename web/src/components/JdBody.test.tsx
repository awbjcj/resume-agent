import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JdBody } from "./JdBody";

describe("JdBody", () => {
  it("keeps newline-heavy legacy text on separate lines (no run-on)", () => {
    const { container } = render(<JdBody text={"Line one\nLine two\nLine three"} />);
    expect(container.querySelectorAll("br").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Line one/)).toBeInTheDocument();
    expect(screen.getByText(/Line three/)).toBeInTheDocument();
  });

  it("renders a real markdown list as <li> items", () => {
    const { container } = render(<JdBody text={"## Skills\n\n- Python\n- Go"} />);
    expect(container.querySelectorAll("li").length).toBe(2);
    expect(screen.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
  });
});
