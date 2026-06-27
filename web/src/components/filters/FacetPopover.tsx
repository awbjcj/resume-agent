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
  open: boolean;
  onOpenChange: (open: boolean) => void;
  getLabel?: (value: string) => string;
  presentation?: "chip" | "field";
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
}: FacetPopoverProps) {
  const [query, setQuery] = useState("");
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
    if (!open) {
      // The controlled close boundary intentionally starts a fresh search session.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQuery("");
    }
  }, [open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) setQuery("");
    onOpenChange(nextOpen);
  };

  const toggle = (option: string) => {
    const next = new Set(selected);
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange(next);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size={presentation === "field" ? "default" : "sm"}
            className={cn(
              presentation === "field"
                ? "h-10 w-full justify-between"
                : "rounded-full",
              selected.size > 0 && "border-primary text-primary",
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
        className="w-80 max-w-[calc(100vw-2rem)] gap-0 overflow-hidden p-0"
      >
        <PopoverHeader className="gap-2 p-4 pb-3">
          <div className="flex items-center justify-between gap-3">
            <PopoverTitle>Filter by {label}</PopoverTitle>
            <Badge variant="secondary">
              {selected.size} selected
            </Badge>
          </div>
          <PopoverDescription>Select options to narrow this view.</PopoverDescription>
        </PopoverHeader>

        <Command>
          <CommandInput
            placeholder={`Search ${label.toLowerCase()}...`}
            aria-label={`Search ${label}`}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList className="max-h-64">
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

        <div className="flex items-center justify-between gap-2 border-t bg-muted/30 p-2">
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
