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

  it("groups consecutive reasoning and tool work into one activity region", () => {
    render(
      <ChatMessage
        showReasoning
        message={{
          id: "a-activity",
          role: "assistant",
          parts: [
            { kind: "reasoning", text: "Choosing sources" },
            {
              kind: "tool",
              callId: "tool-activity",
              name: "check_source",
              argsPreview: "example.com",
              resultPreview: "Verified",
              ok: true,
              done: true,
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByRole("region", { name: "Agent activity" })).toHaveLength(1);
    expect(screen.getByText("1 completed")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeVisible();
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

  it("anchors assistant turns left and user turns right", () => {
    const { rerender } = render(
      <ChatMessage
        showReasoning
        message={{ id: "a3", role: "assistant", parts: [{ kind: "text", text: "A clear follow-up." }] }}
      />,
    );
    expect(screen.getByTestId("chat-message")).toHaveClass("justify-start");

    rerender(
      <ChatMessage
        showReasoning
        message={{ id: "u2", role: "user", parts: [{ kind: "text", text: "My answer." }] }}
      />,
    );
    const message = screen.getByTestId("chat-message");
    expect(message).toHaveClass("justify-end");
    expect(message.firstElementChild).toHaveTextContent("My answer.");
  });
});
