import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FitMeter } from "./FitMeter";

describe("FitMeter", () => {
  it("shows the numeric score", () => {
    render(<FitMeter score={72} />);
    expect(screen.getByText("72")).toBeInTheDocument();
  });

  it("renders an em dash when score is null", () => {
    render(<FitMeter score={null} />);
    expect(screen.getByText("\u2014")).toBeInTheDocument();
  });

  it("exposes an accessible label", () => {
    render(<FitMeter score={50} />);
    expect(screen.getByLabelText(/fit score 50/i)).toBeInTheDocument();
  });
});
