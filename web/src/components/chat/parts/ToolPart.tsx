import { Check, Loader2, X } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { ChatPart } from "@/lib/chat/events";

type ToolChatPart = Extract<ChatPart, { kind: "tool" }>;

export function ToolPart({ part }: { part: ToolChatPart }) {
  return (
    <Collapsible data-testid="chat-part-tool">
      <CollapsibleTrigger className="flex max-w-full items-center gap-2 rounded-full border bg-background/70 px-2.5 py-1 text-xs text-muted-foreground">
        {!part.done ? (
          <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden="true" />
        ) : part.ok ? (
          <Check className="size-3 shrink-0" aria-hidden="true" />
        ) : (
          <X className="size-3 shrink-0 text-destructive" aria-hidden="true" />
        )}
        <span className="font-medium text-foreground">{part.name}</span>
        {part.argsPreview ? <span className="max-w-56 truncate">{part.argsPreview}</span> : null}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
        {part.resultPreview || "Waiting for result…"}
      </CollapsibleContent>
    </Collapsible>
  );
}
