import { useEffect, useMemo, useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type FacetPopoverProps = {
  label: string;
  counts: Record<string, number>;
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  getLabel?: (value: string) => string;
  presentation?: "chip" | "field";
  className?: string;
};

export function FacetPopover({
  label,
  counts,
  selected,
  onChange,
  open,
  onOpenChange,
  getLabel,
  presentation = "chip",
  className,
}: FacetPopoverProps) {
  const [query, setQuery] = useState("");
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const isControlled = open !== undefined;
  const resolvedOpen = isControlled ? open : uncontrolledOpen;
  // Counts refresh live while the popover is open. The server computes each
  // facet leave-one-out (its own selection excluded), so an open facet's
  // options never vanish or reorder as you toggle them — only their numbers
  // move to track the rest of the filter state.
  const options = useMemo(
    () =>
      Object.entries(counts)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([value]) => value),
    [counts],
  );
  const shown = options.filter((option) =>
    (getLabel ? getLabel(option) : option).toLowerCase().includes(query.toLowerCase()),
  );

  useEffect(() => {
    if (!resolvedOpen) {
      // The controlled close boundary intentionally starts a fresh search session.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQuery("");
    }
  }, [resolvedOpen]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) setQuery("");
    if (!isControlled) setUncontrolledOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  const toggle = (option: string) => {
    const next = new Set(selected);
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange(next);
  };

  return (
    <Popover open={resolvedOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            className={cn(
              presentation === "field" ? "w-full justify-between" : "rounded-full",
              selected.size > 0 && "border-primary text-primary",
              className,
            )}
          />
        }
      >
        <span className="truncate">{label}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {selected.size > 0 && <Badge variant="secondary">{selected.size}</Badge>}
          <ChevronDownIcon data-icon="inline-end" />
        </span>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        side="bottom"
        className="max-h-[var(--available-height)] w-80 max-w-[calc(100vw-2rem)] gap-0 overflow-hidden p-0"
      >
        <PopoverHeader className="shrink-0 gap-2 p-4 pb-3">
          <div className="flex items-center justify-between gap-3">
            <PopoverTitle>Filter by {label}</PopoverTitle>
            <Badge variant="secondary">
              {selected.size} selected
            </Badge>
          </div>
          <PopoverDescription>Select options to narrow this view.</PopoverDescription>
        </PopoverHeader>

        <Command className="min-h-0 flex-1">
          <CommandInput
            placeholder={`Search ${label.toLowerCase()}...`}
            aria-label={`Search ${label}`}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList className="min-h-0 max-h-64 flex-1">
            {shown.length === 0 && (
              <CommandEmpty>No matching {label.toLowerCase()}</CommandEmpty>
            )}
            <CommandGroup role="group" aria-label={`${label} options`} className="flex flex-col gap-1">
              {shown.map((option) => {
                const checked = selected.has(option);
                const optionLabel = getLabel ? getLabel(option) : option;
                return (
                  <CommandItem
                    key={option}
                    value={option}
                    role="checkbox"
                    aria-checked={checked}
                    onSelect={() => toggle(option)}
                  >
                    <Checkbox checked={checked} readOnly aria-hidden tabIndex={-1} />
                    <span className="flex-1 truncate">{optionLabel}</span>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {counts[option]}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>

        <div className="flex shrink-0 items-center justify-between gap-2 border-t bg-muted/30 p-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Clear ${label} filter`}
            disabled={selected.size === 0}
            onClick={() => onChange(new Set())}
          >
            Clear
          </Button>
          <Button
            type="button"
            size="sm"
            aria-label={`Done filtering ${label}`}
            onClick={() => handleOpenChange(false)}
          >
            Done
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
