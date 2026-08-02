import { Check, ChevronRight, Loader2, X } from "lucide-react";

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
    <Collapsible data-testid="chat-part-tool" className="min-w-0">
      <CollapsibleTrigger className="group/activity flex max-w-full items-center gap-2 rounded-lg border bg-muted/35 px-2.5 py-1.5 text-xs text-muted-foreground transition-[background-color,border-color,color] duration-[160ms] ease-out-strong hover:bg-muted/60">
        {!part.done ? (
          <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden="true" />
        ) : part.ok ? (
          <Check className="size-3 shrink-0" aria-hidden="true" />
        ) : (
          <X className="size-3 shrink-0 text-destructive" aria-hidden="true" />
        )}
        <span className="font-medium capitalize text-foreground">{label}</span>
        {part.argsPreview ? <span className="max-w-56 truncate">{part.argsPreview}</span> : null}
        <span className="sr-only" aria-live="polite">{label}: {status}</span>
        <ChevronRight className="ml-auto size-3 shrink-0 transition-transform duration-[160ms] ease-out-strong group-data-panel-open/activity:rotate-90 motion-reduce:transition-none" aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted className="mt-1 translate-y-0 overflow-hidden rounded-lg bg-muted/55 p-2 text-xs whitespace-pre-wrap text-muted-foreground opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity">
        {part.resultPreview || "Waiting for result…"}
      </CollapsibleContent>
    </Collapsible>
  );
}
