import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export function MultiSelect({
  label,
  options,
  selected,
  onChange,
  disabled,
  getLabel,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  disabled?: boolean;
  getLabel?: (value: string) => string;
}) {
  const id = `ms-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const toggle = (opt: string) => {
    const next = new Set(selected);
    if (next.has(opt)) next.delete(opt);
    else next.add(opt);
    onChange(next);
  };
  const triggerLabel = selected.size ? `${selected.size} selected` : "Any";
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs font-semibold uppercase tracking-[0.14em]">
        {label}
      </Label>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              id={id}
              variant="outline"
              disabled={disabled}
              className="h-10 w-full justify-between bg-card px-3 font-normal"
            >
              <span>{triggerLabel}</span>
            </Button>
          }
        />
        <DropdownMenuContent className="max-h-72 min-w-56 overflow-auto">
          {options.map((opt) => (
            <DropdownMenuCheckboxItem
              key={opt}
              checked={selected.has(opt)}
              onCheckedChange={() => toggle(opt)}
            >
              {getLabel ? getLabel(opt) : opt.replace(/_/g, " ")}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
