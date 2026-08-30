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
import { fieldLabel } from "@/lib/format";
import { useTranslation } from "react-i18next";
import { TARGET_STATUSES, type Filters as FilterValue } from "./aggregate";

const ALL = "__all__";

/**
 * A compact desktop row that becomes a deliberate two-column control grid on
 * portable widths. Controls keep their own visible or accessible names while
 * avoiding the unpredictable wrapping of one long flex line.
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
  const { t } = useTranslation();
  const companyItems = [
    { label: "All companies", value: ALL },
    ...companies.map((company) => ({ label: company, value: company })),
  ];
  const seniorityItems = [
    { label: "All levels", value: ALL },
    ...seniorities.map((seniority) => ({ label: fieldLabel(seniority), value: seniority })),
  ];

  return (
    <div
      role="group"
      aria-label="Skill filters"
      className="grid min-w-0 flex-1 grid-cols-2 gap-2 lg:flex lg:flex-wrap lg:items-center"
    >
      <Input
        id="match-gap-q"
        type="search"
        aria-label="Search skills"
        placeholder="Search skills…"
        className="col-span-2 h-9 w-full min-w-0 bg-background sm:col-span-1 lg:w-44"
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
          className="w-full min-w-0 bg-background lg:w-36"
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
          className="w-full min-w-0 bg-background lg:w-32"
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
        presentation="field"
        className="w-full lg:w-auto lg:rounded-full"
        counts={{
          ...Object.fromEntries(TARGET_STATUSES.map((status) => [status, 0])),
          ...statusCounts,
        }}
        selected={value.statuses}
        onChange={(statuses) => onChange({ ...value, statuses })}
        getLabel={(stage) => pipelineStageLabel(stage, (key) => t(key))}
      />

      <div className="flex h-9 items-center justify-between gap-2 rounded-lg border bg-background px-3 whitespace-nowrap lg:justify-start lg:border-0 lg:bg-transparent lg:px-0">
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
        className="col-span-2 grid grid-cols-2 lg:flex"
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
