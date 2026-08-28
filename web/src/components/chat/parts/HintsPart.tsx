import { useState } from "react";
import { ChevronDown, Lightbulb } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function HintsPart({ hints }: { hints: string[] }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-xl border border-amber-500/20 bg-amber-500/[0.045]">
      <CollapsibleTrigger
        aria-label="Answer hints"
        className="group/hints flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-amber-500/[0.06] focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-300">
          <Lightbulb className="size-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-foreground">Answer hints</span>
          <span className="block text-xs leading-5 text-muted-foreground">
            {hints.length} ideas to help you shape your response
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-panel-open/hints:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-starting-style:h-0 data-ending-style:h-0">
        <ul className="space-y-2 border-t border-amber-500/15 px-4 py-3 text-sm leading-6 text-muted-foreground">
          {hints.map((hint, index) => (
            <li key={`${index}-${hint}`} className="flex gap-2.5">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden="true" />
              <span>{hint}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
