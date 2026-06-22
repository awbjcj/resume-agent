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
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              id={id}
              variant="outline"
              disabled={disabled}
              className="w-full justify-start font-normal"
            >
              {selected.size ? `${selected.size} selected` : "Any"}
            </Button>
          }
        />
        <DropdownMenuContent className="max-h-64 overflow-auto">
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
