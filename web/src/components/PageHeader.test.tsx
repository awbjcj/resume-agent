import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("title is the single h1; kicker is not a heading", () => {
    render(
      <PageHeader kicker="Human checkpoint" title="The Shortlist" sub="Approve keepers." />,
    );

    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("The Shortlist");
    expect(screen.getByText("Human checkpoint").tagName).not.toMatch(/^H[1-6]$/);
  });
});
