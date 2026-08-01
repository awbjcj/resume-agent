import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function ReasoningPart({ text }: { text: string }) {
  return (
    <Collapsible data-testid="chat-part-reasoning">
      <CollapsibleTrigger className="text-xs text-muted-foreground underline-offset-2 hover:underline">
        Show reasoning
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
        {text}
      </CollapsibleContent>
    </Collapsible>
  );
}
