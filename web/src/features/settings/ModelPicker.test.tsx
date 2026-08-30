import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { changeLanguage } from "@/i18n";
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

  describe("DeepSeek pricing badge", () => {
    beforeEach(() => {
      // Only Date is faked — the Select popup's own content (including this
      // badge) mounts lazily on open, and userEvent's internal waiting needs
      // real setTimeout/requestAnimationFrame to ever resolve.
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date("2026-08-17T02:00:00Z")); // a peak-hour moment
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows live peak/off-peak status only in the DeepSeek group", async () => {
      const catalog: ProviderModelCatalog[] = [
        ...CATALOG,
        {
          provider: "deepseek",
          label: "DeepSeek",
          hasKey: true,
          models: [
            {
              id: "deepseek:deepseek-v4-flash",
              label: "DeepSeek V4 Flash",
              supportsReasoning: false,
              supportsNativeSearch: false,
              reasoningEfforts: ["none", "low", "high", "max"],
            },
          ],
        },
      ];
      const user = userEvent.setup();
      render(<ModelPicker value={KNOWN_MODEL} onChange={vi.fn()} catalog={catalog} />);

      await user.click(screen.getByRole("combobox"));

      const openaiGroup = screen.getByRole("group", { name: /OpenAI/ });
      expect(within(openaiGroup).queryByText("Peak")).not.toBeInTheDocument();
      const deepseekGroup = screen.getByRole("group", { name: /DeepSeek/ });
      expect(within(deepseekGroup).getByText("Peak")).toBeInTheDocument();
    });
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
    await user.click(within(effortGroup).getByRole("button", { name: "Extra high" }));
    expect(onEffort).toHaveBeenCalledWith("xhigh");
  });

  it("localizes model capability and reasoning labels without changing their values", async () => {
    await changeLanguage("zh-CN");
    const user = userEvent.setup();
    const onEffort = vi.fn();
    render(
      <>
        <ModelPicker value={KNOWN_MODEL} onChange={vi.fn()} catalog={CATALOG} />
        <ModelTuningControls
          modelId={KNOWN_MODEL}
          reasoningEffort={null}
          catalog={CATALOG}
          onReasoningEffortChange={onEffort}
        />
      </>,
    );

    await user.click(screen.getByRole("combobox"));
    expect(await screen.findByText("推理")).toBeInTheDocument();
    expect(screen.getByText("搜索")).toBeInTheDocument();

    const effortGroup = screen.getByRole("group", { name: "推理强度" });
    await user.click(within(effortGroup).getByRole("button", { name: "极高" }));
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
