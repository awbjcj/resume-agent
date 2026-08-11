import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { TagListInput } from "./TagListInput";

function Harness() {
  const [value, setValue] = useState<string[]>([]);
  return (
    <>
      <TagListInput id="tags" value={value} onChange={setValue} />
      <output data-testid="tags">{value.join("|")}</output>
    </>
  );
}

describe("TagListInput", () => {
  it("splits a pasted comma-separated string into trimmed tags", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.paste("Python, Django , Kubernetes,Go");
    await user.tab();
    expect(screen.getByTestId("tags")).toHaveTextContent(
      "Python|Django|Kubernetes|Go"
    );
  });

  it("drops empty segments and duplicate tags from a paste", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.paste("python,, python , django");
    await user.tab();
    expect(screen.getByTestId("tags")).toHaveTextContent("python|django");
  });

  it("still commits a single word on Enter", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("textbox"), "python{Enter}");
    expect(screen.getByTestId("tags")).toHaveTextContent("python");
  });
});
