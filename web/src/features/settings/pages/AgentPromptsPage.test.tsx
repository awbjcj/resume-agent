import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentPromptsPage } from "./AgentPromptsPage";

const save = vi.fn();
const items = [
  {
    key: "tailor-writer",
    title: "Resume writer",
    stage: "tailoring",
    description: "Writes the targeted resume.",
    instructions: ["Rule one.", "Rule two."],
    guidance: null,
    editable: true,
  },
  {
    key: "reviewer-fact-check",
    title: "Fact-check gate",
    stage: "review",
    description: "Hard integrity gate.",
    instructions: ["Verify every claim."],
    guidance: null,
    editable: false,
  },
];

vi.mock("../use-prompts", () => ({
  usePrompts: () => ({ data: items, isPending: false, isError: false }),
  useSaveGuidance: () => ({ mutate: save, isPending: false }),
}));

describe("AgentPromptsPage", () => {
  beforeEach(() => save.mockClear());

  it("groups agents and reveals immutable base instructions", async () => {
    render(<AgentPromptsPage />);
    expect(screen.getByRole("heading", { name: "Tailoring" })).toBeInTheDocument();
    await userEvent.click(screen.getByText("Resume writer"));
    expect(screen.getByText("Rule one.")).toBeInTheDocument();
  });

  it("saves editable guidance and keeps integrity gates read-only", async () => {
    render(<AgentPromptsPage />);
    await userEvent.click(screen.getByText("Resume writer"));
    await userEvent.type(screen.getByLabelText("Your guidance for Resume writer"), "Punchy verbs.");
    await userEvent.click(screen.getByRole("button", { name: "Save guidance" }));
    expect(save).toHaveBeenCalledWith({
      key: "tailor-writer",
      guidance: "Punchy verbs.",
    });

    await userEvent.click(screen.getByText("Fact-check gate"));
    expect(screen.getByText("Integrity gate — read-only")).toBeInTheDocument();
    expect(screen.queryByLabelText(/guidance for Fact-check/i)).not.toBeInTheDocument();
  });
});
