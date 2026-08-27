import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { defaultTargetStatuses } from "./aggregate";
import { Filters } from "./Filters";

describe("Filters", () => {
  it("shows user-facing labels for unfiltered select values", () => {
    render(
      <Filters
        value={{
          q: "",
          company: null,
          seniority: null,
          statuses: defaultTargetStatuses(),
          gapsOnly: false,
          weighting: "essential",
        }}
        onChange={() => {}}
        companies={["Stripe"]}
        seniorities={["senior"]}
        statusCounts={{}}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Filter by company" })).toHaveTextContent(
      "All companies",
    );
    expect(screen.getByRole("combobox", { name: "Filter by seniority" })).toHaveTextContent(
      "All levels",
    );
    expect(screen.getByRole("group", { name: "Skill filters" })).toHaveClass("grid-cols-2");
    expect(screen.getByRole("button", { name: /^Stage/ })).toHaveClass("w-full");
  });
});
