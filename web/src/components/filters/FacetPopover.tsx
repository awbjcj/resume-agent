import { useMemo, useState } from "react";
import { CheckIcon, ChevronDownIcon } from "lucide-react";

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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function FacetPopover({
  label,
  counts,
  selected,
  onChange,
  getLabel,
}: {
  label: string;
  counts: Record<string, number>;
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  getLabel?: (value: string) => string;
}) {
  const [q, setQ] = useState("");
  const options = useMemo(
    () => Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k),
    [counts],
  );
  const shown = options.filter((option) =>
    (getLabel ? getLabel(option) : option).toLowerCase().includes(q.toLowerCase()),
  );
  const toggle = (option: string) => {
    const next = new Set(selected);
    if (next.has(option)) next.delete(option);
    else next.add(option);
    onChange(next);
  };

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            className={cn("rounded-full", selected.size > 0 && "border-primary text-primary")}
          >
            {label}
            {selected.size > 0 && <Badge variant="secondary">{selected.size}</Badge>}
            <ChevronDownIcon data-icon="inline-end" />
          </Button>
        }
      />
      <PopoverContent align="start" className="w-72 p-0">
        <Command>
          <CommandInput
            placeholder={`Search ${label.toLowerCase()}...`}
            value={q}
            onValueChange={setQ}
          />
          <CommandList>
            {shown.length === 0 && <CommandEmpty>No matches</CommandEmpty>}
            <CommandGroup>
              {shown.map((option) => {
                const checked = selected.has(option);
                return (
                  <CommandItem key={option} value={option} onSelect={() => toggle(option)}>
                    <Checkbox checked={checked} aria-hidden />
                    <span className="flex-1 truncate">{getLabel ? getLabel(option) : option}</span>
                    <span className="text-xs text-muted-foreground">{counts[option]}</span>
                    {checked && <CheckIcon className="text-primary" />}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
