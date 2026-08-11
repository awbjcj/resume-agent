import { Check, ChevronDown, Loader2, Wrench, X } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { ChatPart } from "@/lib/chat/events";

type ToolChatPart = Extract<ChatPart, { kind: "tool" }>;

export function ToolPart({ part }: { part: ToolChatPart }) {
  const label = part.name.replaceAll("_", " ");
  const status = part.done ? (part.ok ? "Completed" : "Failed") : "Working";
  return (
    <Collapsible data-testid="chat-part-tool" className="min-w-0 py-2.5">
      <CollapsibleTrigger className="group/activity flex min-h-10 w-full items-center gap-3 rounded-lg px-1.5 text-left text-sm transition-colors duration-[160ms] ease-out-strong hover:bg-muted/55 focus-visible:outline-2 focus-visible:outline-offset-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-background shadow-sm">
        {!part.done ? (
          <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden="true" />
        ) : part.ok ? (
          <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
        ) : (
          <X className="size-3.5 text-destructive" aria-hidden="true" />
        )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium capitalize text-foreground">{label}</span>
          <span className="flex min-w-0 items-center gap-2 text-[0.8125rem] leading-5 text-muted-foreground">
            <span className="shrink-0 text-[0.75rem] font-medium">{status}</span>
            {part.argsPreview ? <span className="truncate">{part.argsPreview}</span> : null}
          </span>
        </span>
        <span className="sr-only" aria-live="polite">{label}: {status}</span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform duration-[180ms] ease-out-strong group-data-panel-open/activity:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted className="translate-y-0 overflow-hidden opacity-100 transition-[opacity,transform] duration-[180ms] ease-out-strong will-change-[opacity,transform] data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity">
        <div className="ml-10 mt-1 flex items-start gap-2 border-l-2 border-primary/20 py-1 pl-3 font-mono text-[0.8125rem] leading-6 text-muted-foreground">
          <Wrench className="mt-1 size-3 shrink-0" aria-hidden="true" />
          <span className="min-w-0 whitespace-pre-wrap break-words">{part.resultPreview || "Waiting for result…"}</span>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
