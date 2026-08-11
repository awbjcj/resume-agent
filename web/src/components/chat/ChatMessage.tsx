import { memo, type ReactNode } from "react";
import { Bot, UserRound } from "lucide-react";

import type { ChatPart } from "@/lib/chat/events";
import { cn } from "@/lib/utils";

import type { ChatThreadMessage } from "./ChatThread";
import { AgentActivity } from "./AgentActivity";
import { NoticePart } from "./parts/NoticePart";
import { TextPart } from "./parts/TextPart";

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
  const rendered: ReactNode[] = [];
  for (let index = 0; index < visible.length;) {
    const part = visible[index]!;
    if (part.kind === "tool" || part.kind === "reasoning") {
      const activity = [];
      let next = index;
      while (next < visible.length) {
        const candidate = visible[next]!;
        if (candidate.kind !== "tool" && candidate.kind !== "reasoning") break;
        activity.push(candidate);
        next += 1;
      }
      rendered.push(<AgentActivity key={`${message.id}-activity-${index}`} parts={activity} />);
      index = next;
      continue;
    }
    const key = `${message.id}-${index}`;
    rendered.push(part.kind === "text" ? (
      <TextPart key={key} text={part.text} caret={streaming && index === visible.length - 1} />
    ) : (
      <NoticePart key={key} message={part.message} />
    ));
    index += 1;
  }
  const avatar = (
    <div className={cn(
      "flex size-9 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-sm",
      assistant ? "absolute left-0 top-0 border-primary/20 bg-primary/[0.08] text-primary sm:static" : "mt-1",
    )}>
      {assistant ? assistantIcon ?? <Bot className="size-4" aria-hidden="true" /> : <UserRound className="size-4" aria-hidden="true" />}
    </div>
  );
  return (
    <article data-testid="chat-message" className={cn(
      "w-full items-start gap-3 sm:gap-3.5",
      assistant ? "relative block justify-start sm:flex" : "flex justify-end",
    )}>
      {assistant ? avatar : null}
      <div className={cn(
        "min-w-0 max-w-[min(56rem,calc(100%-3rem))]",
        assistant ? "w-full lg:max-w-[min(62rem,82%)]" : "flex flex-col items-end lg:max-w-[min(48rem,72%)]",
      )}>
        {assistant ? (
          <div className="mb-2 flex min-h-9 items-center gap-2 pl-12 sm:min-h-5 sm:px-0.5">
            <span className="text-[0.8125rem] font-semibold tracking-[-0.01em] text-foreground">{assistantName}</span>
            {streaming ? (
              <span className="flex items-center gap-1.5 text-[0.75rem] text-muted-foreground" role="status">
                <span className="size-1.5 rounded-full bg-primary motion-safe:animate-pulse" aria-hidden="true" />
                Responding
              </span>
            ) : null}
          </div>
        ) : null}
        <div className={cn(
          "space-y-4 text-base leading-7",
          assistant
            ? "rounded-xl border border-border/80 bg-card/80 px-4 py-4 shadow-card sm:px-5"
            : "rounded-2xl rounded-tr-md bg-primary/10 px-4 py-3.5 shadow-sm",
        )}>
          {rendered}
        </div>
      </div>
      {!assistant ? avatar : null}
    </article>
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
