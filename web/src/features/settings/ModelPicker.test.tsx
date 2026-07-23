import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ModelPicker } from "./ModelPicker";
import type { ProviderModelCatalog } from "./use-model-catalog";

const KNOWN_MODEL = "openai:gpt-5.5";
const CATALOG: ProviderModelCatalog[] = [
  {
    provider: "openai",
    label: "OpenAI",
    hasKey: true,
    models: [
      {
        id: KNOWN_MODEL,
        label: "GPT-5.5",
        supportsReasoning: true,
        supportsNativeSearch: true,
      },
    ],
  },
];

function Harness() {
  const [value, setValue] = useState(KNOWN_MODEL);
  return (
    <>
      <ModelPicker value={value} onChange={setValue} catalog={CATALOG} />
      <button type="button" onClick={() => setValue(KNOWN_MODEL)}>Discard</button>
    </>
  );
}

describe("ModelPicker", () => {
  it("leaves custom mode when the parent restores a catalog value", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Custom model id…" }));
    const input = screen.getByPlaceholderText(/provider:model-id/);
    await user.clear(input);
    await user.type(input, "openai:custom-model");

    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(screen.queryByPlaceholderText(/provider:model-id/)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveTextContent("GPT-5.5");
  });
});
