import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Filters } from "./Filters";

describe("Filters", () => {
  it("shows user-facing labels for unfiltered select values", () => {
    render(
      <Filters
        value={{ company: null, seniority: null, gapsOnly: false, weighting: "essential" }}
        onChange={() => {}}
        companies={["Stripe"]}
        seniorities={["senior"]}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Filter by company" })).toHaveTextContent(
      "All companies",
    );
    expect(screen.getByRole("combobox", { name: "Filter by seniority" })).toHaveTextContent(
      "All levels",
    );
  });
});
