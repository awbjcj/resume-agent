import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ChatMessage } from "./ChatMessage";

describe("ChatMessage", () => {
  it("renders a named assistant and structured tool status", async () => {
    const user = userEvent.setup();
    render(
      <ChatMessage
        assistantName="Discovery Scout"
        showReasoning
        message={{
          id: "a1",
          role: "assistant",
          parts: [{
            kind: "tool",
            callId: "tool-1",
            name: "search_jobs",
            argsPreview: "remote climate",
            resultPreview: "12 matches",
            ok: true,
            done: true,
          }],
        }}
      />,
    );
    expect(screen.getByText("Discovery Scout")).toBeInTheDocument();
    expect(screen.getByText("search jobs")).toBeInTheDocument();
    expect(screen.getByText("search jobs: Completed")).toHaveClass("sr-only");
    await user.click(screen.getByRole("button", { name: /search jobs/i }));
    expect(screen.getByText("12 matches")).toBeVisible();
  });

  it("keeps reasoning in an accessible disclosure", async () => {
    const user = userEvent.setup();
    render(
      <ChatMessage
        showReasoning
        message={{ id: "a2", role: "assistant", parts: [{ kind: "reasoning", text: "Checking evidence" }] }}
      />,
    );
    expect(screen.getByText("Checking evidence")).not.toBeVisible();
    await user.click(screen.getByRole("button", { name: "Working notes" }));
    expect(screen.getByText("Checking evidence")).toBeVisible();
  });

  it("does not add an assistant label to user messages", () => {
    render(
      <ChatMessage
        assistantName="Interviewer"
        showReasoning
        message={{ id: "u1", role: "user", parts: [{ kind: "text", text: "My answer" }] }}
      />,
    );
    expect(screen.getByText("My answer")).toBeInTheDocument();
    expect(screen.queryByText("Interviewer")).not.toBeInTheDocument();
  });
});
