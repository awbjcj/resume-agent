import { ListChecks } from "lucide-react";

import type { ChatPart } from "@/lib/chat/events";

import { ReasoningPart } from "./parts/ReasoningPart";
import { ToolPart } from "./parts/ToolPart";

type ActivityPart = Extract<ChatPart, { kind: "reasoning" | "tool" }>;

export function AgentActivity({ parts }: { parts: ActivityPart[] }) {
  const working = parts.some((part) => part.kind === "tool" && !part.done);
  const completed = parts.filter((part) => part.kind === "tool" && part.done && part.ok).length;

  return (
    <section
      aria-label="Agent activity"
      data-testid="chat-agent-activity"
      className="overflow-hidden rounded-xl border bg-muted/25"
    >
      <div className="flex min-h-10 items-center gap-2.5 border-b bg-muted/35 px-3.5 py-2">
        <ListChecks className="size-4 shrink-0 text-primary" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-[-0.01em] text-foreground">Agent activity</span>
        <span className="ml-auto flex items-center gap-1.5 text-[0.8125rem] text-muted-foreground">
          {working ? (
            <>
              <span className="size-1.5 rounded-full bg-primary motion-safe:animate-pulse" aria-hidden="true" />
              Working
            </>
          ) : completed ? `${completed} completed` : "Notes ready"}
        </span>
      </div>
      <div className="divide-y divide-border/70 px-3.5">
        {parts.map((part, index) => part.kind === "tool" ? (
          <ToolPart key={`${part.callId}-${index}`} part={part} />
        ) : (
          <ReasoningPart key={`reasoning-${index}`} text={part.text} />
        ))}
      </div>
    </section>
  );
}
