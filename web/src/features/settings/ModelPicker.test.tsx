import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelPicker, ModelTuningControls } from "./ModelPicker";
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
        reasoningEfforts: ["none", "low", "medium", "high", "xhigh"],
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
    await user.click(await screen.findByRole("option", { name: "Custom model id…" }));
    const input = screen.getByPlaceholderText(/provider:model-id/);
    await user.clear(input);
    await user.type(input, "openai:custom-model");

    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(screen.queryByPlaceholderText(/provider:model-id/)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveTextContent("GPT-5.5");
  });

  it("lets the user pick a reasoning effort level", async () => {
    const user = userEvent.setup();
    const onEffort = vi.fn();
    render(
      <ModelTuningControls
        modelId={KNOWN_MODEL}
        reasoningEffort={null}
        catalog={CATALOG}
        onReasoningEffortChange={onEffort}
      />,
    );

    const effortGroup = screen.getByRole("group", { name: "Effort" });
    await user.click(within(effortGroup).getByRole("button", { name: "Xhigh" }));
    expect(onEffort).toHaveBeenCalledWith("xhigh");
  });

  it("renders nothing when the selected model has no reasoning effort levels", () => {
    const onEffort = vi.fn();
    const { container } = render(
      <ModelTuningControls
        modelId="openai:no-reasoning"
        reasoningEffort={null}
        catalog={[
          {
            provider: "openai",
            label: "OpenAI",
            hasKey: true,
            models: [
              {
                id: "openai:no-reasoning",
                label: "No Reasoning",
                supportsReasoning: false,
                supportsNativeSearch: false,
                reasoningEfforts: [],
              },
            ],
          },
        ]}
        onReasoningEffortChange={onEffort}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
