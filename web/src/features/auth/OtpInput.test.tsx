import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { OtpInput } from "./OtpInput";

function Harness() {
  const [value, setValue] = useState("");
  return <OtpInput label="Verification code" value={value} onChange={setValue} />;
}

describe("OtpInput", () => {
  it("accepts pasted digits and does not shift later digits on a middle edit", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const boxes = screen.getAllByRole("textbox");
    await user.click(boxes[0]);
    await user.paste("482913");
    expect(boxes.map((box) => (box as HTMLInputElement).value).join("")).toBe("482913");
    await user.click(boxes[2]);
    await user.keyboard("{Backspace}");
    expect(boxes[0]).toHaveValue("4");
    expect(boxes[1]).toHaveValue("8");
    expect(boxes[2]).toHaveValue("");
    expect(boxes[3]).toHaveValue("");
  });
});
