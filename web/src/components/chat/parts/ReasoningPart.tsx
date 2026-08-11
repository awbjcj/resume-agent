import { useState } from "react";
import { BrainCircuit, ChevronDown } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function ReasoningPart({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible data-testid="chat-part-reasoning" open={open} onOpenChange={setOpen} className="py-2.5">
      <CollapsibleTrigger aria-label="Working notes" className="group/activity flex min-h-10 w-full items-center gap-3 rounded-lg px-1.5 text-left text-sm transition-colors duration-[160ms] ease-out-strong hover:bg-muted/55 focus-visible:outline-2 focus-visible:outline-offset-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-background text-primary shadow-sm">
          <BrainCircuit className="size-3.5" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-foreground">Working notes</span>
          <span className="block truncate text-[0.8125rem] leading-5 text-muted-foreground">Review the agent&apos;s summarized approach</span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform duration-[180ms] ease-out-strong group-data-panel-open/activity:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted className="translate-y-0 overflow-hidden opacity-100 transition-[opacity,transform] duration-[180ms] ease-out-strong will-change-[opacity,transform] data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity">
        <div className="ml-10 mt-1 whitespace-pre-wrap border-l-2 border-primary/20 py-1 pl-3 text-sm leading-6 text-muted-foreground">
          {text}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
