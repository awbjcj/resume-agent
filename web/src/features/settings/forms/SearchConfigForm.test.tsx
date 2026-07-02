import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SearchConfigForm, type SearchDoc } from "./SearchConfigForm";

const EMPTY: SearchDoc = {
  keywords: [], titles: [], locations: [], remotePolicy: null,
  minSalary: null, yoeMin: null, yoeMax: null, sponsorshipRequired: false,
  roleAnchors: [], excludeTerms: [], targetRole: null,
  distance: null, maxDaysOld: null, experienceLevels: [], employmentTypes: [],
};

function Harness() {
  const [value, setValue] = useState(EMPTY);
  return (
    <>
      <SearchConfigForm value={value} onChange={setValue} />
      <output data-testid="keywords">{value.keywords?.join(",")}</output>
      <output data-testid="remote-policy">{value.remotePolicy ?? ""}</output>
    </>
  );
}

describe("SearchConfigForm", () => {
  it("adds a keyword tag on Enter", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Keywords"), "python{Enter}");
    expect(screen.getByTestId("keywords")).toHaveTextContent("python");
  });

  it("removes a tag via its remove button", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Keywords"), "python{Enter}");
    await user.click(screen.getByRole("button", { name: "Remove python" }));
    expect(screen.getByTestId("keywords")).toHaveTextContent("");
  });

  it("selects a single remote policy option and can deselect it back to any", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Remote only" }));
    expect(screen.getByTestId("remote-policy")).toHaveTextContent("remote_only");
    await user.click(screen.getByRole("button", { name: "Hybrid" }));
    expect(screen.getByTestId("remote-policy")).toHaveTextContent("hybrid");
    await user.click(screen.getByRole("button", { name: "Hybrid" }));
    expect(screen.getByTestId("remote-policy")).toHaveTextContent("");
  });
});
