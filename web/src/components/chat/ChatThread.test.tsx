import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatThread } from "./ChatThread";

describe("ChatThread", () => {
  it("renders message and streamed parts in arrival order", () => {
    render(
      <ChatThread
        messages={[{ id: "u", role: "user", parts: [{ kind: "text", text: "hi" }] }]}
        streaming={[
          { kind: "text", text: "checking" },
          {
            kind: "tool",
            callId: "c1",
            name: "search",
            argsPreview: "Kafka",
            resultPreview: "",
            ok: true,
            done: false,
          },
          { kind: "text", text: "done" },
        ]}
      />,
    );
    expect(screen.getAllByTestId(/chat-part-/).map((node) => node.dataset.testid)).toEqual([
      "chat-part-text",
      "chat-part-text",
      "chat-part-tool",
      "chat-part-text",
    ]);
  });

  it("hides reasoning when disabled", () => {
    render(
      <ChatThread
        messages={[]}
        streaming={[{ kind: "reasoning", text: "private" }]}
        showReasoning={false}
      />,
    );
    expect(screen.queryByText("private")).not.toBeInTheDocument();
  });

  it("offers jump to latest after scrolling away", () => {
    render(<ChatThread messages={[]} streaming={null} />);
    const viewport = screen.getByTestId("chat-viewport");
    Object.defineProperties(viewport, {
      scrollHeight: { value: 1000, configurable: true },
      clientHeight: { value: 200, configurable: true },
      scrollTop: { value: 100, configurable: true, writable: true },
    });
    fireEvent.scroll(viewport);
    expect(screen.getByRole("button", { name: /jump to latest/i })).toBeInTheDocument();
  });
});
