import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Filters as FilterValue } from "./aggregate";

const ALL = "__all__";

export function Filters({
  value,
  onChange,
  companies,
  seniorities,
}: {
  value: FilterValue;
  onChange: (next: FilterValue) => void;
  companies: string[];
  seniorities: string[];
}) {
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
      <div className="grid gap-1.5">
        <Label htmlFor="match-gap-company" className="text-xs text-muted-foreground">
          Company
        </Label>
        <Select
          value={value.company ?? ALL}
          onValueChange={(company) =>
            onChange({ ...value, company: company === ALL ? null : company })
          }
        >
          <SelectTrigger id="match-gap-company" className="w-44" aria-label="Filter by company">
            <SelectValue placeholder="Company" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All companies</SelectItem>
            {companies.map((company) => (
              <SelectItem key={company} value={company}>
                {company}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="match-gap-seniority" className="text-xs text-muted-foreground">
          Seniority
        </Label>
        <Select
          value={value.seniority ?? ALL}
          onValueChange={(seniority) =>
            onChange({ ...value, seniority: seniority === ALL ? null : seniority })
          }
        >
          <SelectTrigger
            id="match-gap-seniority"
            className="w-40"
            aria-label="Filter by seniority"
          >
            <SelectValue placeholder="Seniority" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All levels</SelectItem>
            {seniorities.map((seniority) => (
              <SelectItem key={seniority} value={seniority}>
                {seniority}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex h-8 items-center gap-2">
        <Switch
          id="match-gap-gaps-only"
          checked={value.gapsOnly}
          onCheckedChange={(gapsOnly) => onChange({ ...value, gapsOnly })}
        />
        <Label htmlFor="match-gap-gaps-only">Gaps only</Label>
      </div>

      <div className="grid gap-1.5">
        <span className="text-xs text-muted-foreground">Weighting</span>
        <ToggleGroup
          aria-label="Demand weighting"
          value={[value.weighting]}
          onValueChange={(next) => {
            const weighting = next.at(-1) as FilterValue["weighting"] | undefined;
            if (weighting) onChange({ ...value, weighting });
          }}
        >
          <ToggleGroupItem value="essential">Essential</ToggleGroupItem>
          <ToggleGroupItem value="popular">Popular</ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>
  );
}
