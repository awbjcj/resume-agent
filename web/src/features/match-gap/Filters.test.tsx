import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
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

  it("localizes stage facet options in Chinese", async () => {
    const user = userEvent.setup();
    await changeLanguage("zh-CN");

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
        companies={[]}
        seniorities={[]}
        statusCounts={{ shortlisted: 236, tailored: 5, rendered: 4, approved: 2 }}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^阶段/ }));

    expect(screen.getByRole("checkbox", { name: /已加入候选/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /已定制/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /已生成/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /已批准/ })).toBeInTheDocument();
    expect(screen.queryByText("Shortlisted")).not.toBeInTheDocument();
  });
});
