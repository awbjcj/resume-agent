import { useState } from "react";
import { ChevronRight } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function ReasoningPart({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible data-testid="chat-part-reasoning" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group/activity flex items-center gap-1.5 rounded-lg border border-transparent px-2 py-1 text-xs text-muted-foreground transition-[background-color,border-color,color] duration-[160ms] ease-out-strong hover:border-border hover:bg-muted/45">
        <ChevronRight className="size-3 transition-transform duration-[160ms] ease-out-strong group-data-panel-open/activity:rotate-90 motion-reduce:transition-none" aria-hidden="true" />
        Working notes
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted className="mt-1 translate-y-0 overflow-hidden rounded-lg bg-muted/55 p-2 text-xs whitespace-pre-wrap text-muted-foreground opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity">
        {text}
      </CollapsibleContent>
    </Collapsible>
  );
}
