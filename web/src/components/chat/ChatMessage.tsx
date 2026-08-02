import { memo, type ReactNode } from "react";
import { Bot, UserRound } from "lucide-react";

import type { ChatPart } from "@/lib/chat/events";
import { cn } from "@/lib/utils";

import type { ChatThreadMessage } from "./ChatThread";
import { NoticePart } from "./parts/NoticePart";
import { ReasoningPart } from "./parts/ReasoningPart";
import { TextPart } from "./parts/TextPart";
import { ToolPart } from "./parts/ToolPart";

function samePart(left: ChatPart, right: ChatPart): boolean {
  if (left.kind !== right.kind) return false;
  if (left.kind === "text" || left.kind === "reasoning") {
    return right.kind === left.kind && left.text === right.text;
  }
  if (left.kind === "notice") {
    return right.kind === "notice" && left.message === right.message;
  }
  return right.kind === "tool" &&
    left.callId === right.callId &&
    left.name === right.name &&
    left.argsPreview === right.argsPreview &&
    left.resultPreview === right.resultPreview &&
    left.ok === right.ok &&
    left.done === right.done;
}

export const ChatMessage = memo(function ChatMessage({
  message,
  showReasoning,
  streaming = false,
  assistantName = "Assistant",
  assistantIcon,
}: {
  message: ChatThreadMessage;
  showReasoning: boolean;
  streaming?: boolean;
  assistantName?: string;
  assistantIcon?: ReactNode;
}) {
  const assistant = message.role === "assistant";
  const visible = showReasoning
    ? message.parts
    : message.parts.filter((part) => part.kind !== "reasoning");
  return (
    <div data-testid="chat-message" className={cn("flex items-start gap-2 sm:gap-3", !assistant && "flex-row-reverse")}>
      <div className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-sm",
        assistant ? "mt-5 border-primary/20 bg-primary/[0.07] text-primary" : "mt-1",
      )}>
        {assistant ? assistantIcon ?? <Bot className="size-4" aria-hidden="true" /> : <UserRound className="size-4" aria-hidden="true" />}
      </div>
      <div className={cn("min-w-0 max-w-[min(42rem,calc(100%-2.5rem))]", !assistant && "flex flex-col items-end")}>
        {assistant ? <div className="mb-1 px-1 text-[11px] font-semibold tracking-wide text-muted-foreground">{assistantName}</div> : null}
        <div className={cn(
          "space-y-2 rounded-2xl px-3.5 py-2.5 text-sm shadow-sm",
          assistant ? "rounded-tl-sm border bg-card" : "rounded-tr-sm bg-primary/10",
        )}>
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
    </div>
  );
}, (before, after) =>
  before.showReasoning === after.showReasoning &&
  before.streaming === after.streaming &&
  before.message.id === after.message.id &&
  before.message.role === after.message.role &&
  before.assistantName === after.assistantName &&
  before.assistantIcon === after.assistantIcon &&
  before.message.parts.length === after.message.parts.length &&
  before.message.parts.every((part, index) => samePart(part, after.message.parts[index]!))
);
