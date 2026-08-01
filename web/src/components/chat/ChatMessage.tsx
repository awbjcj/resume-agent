import { Bot, UserRound } from "lucide-react";

import { cn } from "@/lib/utils";

import type { ChatThreadMessage } from "./ChatThread";
import { NoticePart } from "./parts/NoticePart";
import { ReasoningPart } from "./parts/ReasoningPart";
import { TextPart } from "./parts/TextPart";
import { ToolPart } from "./parts/ToolPart";

export function ChatMessage({
  message,
  showReasoning,
  streaming = false,
}: {
  message: ChatThreadMessage;
  showReasoning: boolean;
  streaming?: boolean;
}) {
  const assistant = message.role === "assistant";
  const visible = showReasoning
    ? message.parts
    : message.parts.filter((part) => part.kind !== "reasoning");
  return (
    <div
      data-testid="chat-message"
      className={cn("flex items-start gap-2 sm:gap-3", !assistant && "flex-row-reverse")}
    >
      <div className="mt-1 shrink-0 rounded-full border bg-background p-1.5 shadow-sm">
        {assistant ? <Bot className="size-4" /> : <UserRound className="size-4" />}
      </div>
      <div
        className={cn(
          "min-w-0 max-w-[min(42rem,calc(100%-2.5rem))] space-y-2 rounded-2xl px-3.5 py-2.5 text-sm shadow-sm",
          assistant ? "rounded-tl-sm border bg-card" : "rounded-tr-sm bg-primary/10",
        )}
      >
        {visible.map((part, index) => {
          const key = `${message.id}-${index}`;
          if (part.kind === "text") {
            return (
              <TextPart
                key={key}
                text={part.text}
                caret={streaming && index === visible.length - 1}
              />
            );
          }
          if (part.kind === "tool") return <ToolPart key={key} part={part} />;
          if (part.kind === "reasoning") return <ReasoningPart key={key} text={part.text} />;
          return <NoticePart key={key} message={part.message} />;
        })}
      </div>
    </div>
  );
}
