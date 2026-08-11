import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { FacetPopover } from "@/components/filters/FacetPopover";
import { pipelineStageLabel } from "@/features/pipeline/pipeline-stages";
import { TARGET_STATUSES, type Filters as FilterValue } from "./aggregate";

const ALL = "__all__";

/**
 * One compact row. Every control is h-9 and carries its own visible or
 * accessible name -- stacked field labels doubled the row height and forced
 * the group to wrap onto three lines at ordinary widths, which pushed the
 * dashboard itself below the fold on the page this toolbar is sticky over.
 */
export function Filters({
  value,
  onChange,
  companies,
  seniorities,
  statusCounts,
}: {
  value: FilterValue;
  onChange: (next: FilterValue) => void;
  companies: string[];
  seniorities: string[];
  statusCounts: Record<string, number>;
}) {
  const companyItems = [
    { label: "All companies", value: ALL },
    ...companies.map((company) => ({ label: company, value: company })),
  ];
  const seniorityItems = [
    { label: "All levels", value: ALL },
    ...seniorities.map((seniority) => ({ label: seniority, value: seniority })),
  ];

  return (
    <div
      role="group"
      aria-label="Skill filters"
      className="flex min-w-0 flex-1 flex-wrap items-center gap-2"
    >
      <Input
        id="match-gap-q"
        type="search"
        aria-label="Search skills"
        placeholder="Search skills…"
        className="h-9 w-full min-w-0 bg-background sm:w-44"
        value={value.q}
        onChange={(event) => onChange({ ...value, q: event.target.value })}
      />

      <Select
        items={companyItems}
        value={value.company ?? ALL}
        onValueChange={(company) =>
          onChange({ ...value, company: company === ALL ? null : company })
        }
      >
        <SelectTrigger
          id="match-gap-company"
          size="compact"
          className="w-36 min-w-0 bg-background"
          aria-label="Filter by company"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent
          align="start"
          alignItemWithTrigger={false}
          className="w-max min-w-[var(--anchor-width)] max-w-80"
        >
          <SelectGroup>
            {companyItems.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      <Select
        items={seniorityItems}
        value={value.seniority ?? ALL}
        onValueChange={(seniority) =>
          onChange({ ...value, seniority: seniority === ALL ? null : seniority })
        }
      >
        <SelectTrigger
          id="match-gap-seniority"
          size="compact"
          className="w-32 min-w-0 bg-background"
          aria-label="Filter by seniority"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent
          align="start"
          alignItemWithTrigger={false}
          className="w-max min-w-[var(--anchor-width)]"
        >
          <SelectGroup>
            {seniorityItems.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      <FacetPopover
        label="Stage"
        counts={{
          ...Object.fromEntries(TARGET_STATUSES.map((status) => [status, 0])),
          ...statusCounts,
        }}
        selected={value.statuses}
        onChange={(statuses) => onChange({ ...value, statuses })}
        getLabel={pipelineStageLabel}
      />

      <div className="flex h-9 items-center gap-2 whitespace-nowrap">
        <Switch
          id="match-gap-gaps-only"
          checked={value.gapsOnly}
          onCheckedChange={(gapsOnly) => onChange({ ...value, gapsOnly })}
        />
        <Label htmlFor="match-gap-gaps-only" className="text-sm font-medium">
          Gaps only
        </Label>
      </div>

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
  );
}
