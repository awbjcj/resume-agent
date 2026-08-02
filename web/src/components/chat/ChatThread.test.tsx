import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatThread } from "./ChatThread";

const renders = vi.hoisted(() => ({ textParts: 0 }));
vi.mock("./parts/TextPart", () => ({
  TextPart: ({ text, caret }: { text: string; caret?: boolean }) => {
    renders.textParts += 1;
    return <div data-testid="chat-part-text" data-caret={caret}>{text}</div>;
  },
}));

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

  it("does not re-render durable text parts for each streaming delta", () => {
    renders.textParts = 0;
    const messages = Array.from({ length: 20 }, (_, index) => ({
      id: `m-${index}`,
      role: "assistant" as const,
      parts: [{ kind: "text" as const, text: `durable ${index}` }],
    }));
    const { rerender } = render(
      <ChatThread messages={messages} streaming={[{ kind: "text", text: "a" }]} />,
    );
    expect(renders.textParts).toBe(21);
    rerender(
      <ChatThread messages={messages} streaming={[{ kind: "text", text: "ab" }]} />,
    );
    expect(renders.textParts).toBe(22);
  });

  it("clears the caret when prose settles", () => {
    const { rerender } = render(
      <ChatThread messages={[]} streaming={[{ kind: "text", text: "answer" }]} />,
    );
    expect(screen.getByTestId("chat-part-text")).toHaveAttribute("data-caret", "true");
    rerender(
      <ChatThread messages={[]} streaming={[{ kind: "text", text: "answer" }]} streamingActive={false} />,
    );
    expect(screen.getByTestId("chat-part-text")).toHaveAttribute("data-caret", "false");
  });

  it("does not mount reasoning text while its disclosure is collapsed", () => {
    render(<ChatThread messages={[]} streaming={[{ kind: "reasoning", text: "private chain" }]} />);
    expect(screen.queryByText("private chain")).not.toBeInTheDocument();
  });
});
