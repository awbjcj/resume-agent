import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
const CONTROL_LABEL_CLASS =
  "text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground";

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
    <FieldGroup className="w-auto flex-1 flex-row flex-wrap items-end gap-4">
      <Field className="w-full gap-2 sm:w-60">
        <FieldLabel htmlFor="match-gap-q" className={CONTROL_LABEL_CLASS}>
          Search
        </FieldLabel>
        <Input
          id="match-gap-q"
          type="search"
          placeholder="Skill name…"
          className="h-9 bg-background"
          value={value.q}
          onChange={(event) => onChange({ ...value, q: event.target.value })}
        />
      </Field>

      <Field className="w-full gap-2 sm:w-48">
        <FieldLabel htmlFor="match-gap-company" className={CONTROL_LABEL_CLASS}>
          Company
        </FieldLabel>
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
            className="w-full bg-background"
            aria-label="Filter by company"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start" alignItemWithTrigger={false} className="w-max min-w-[var(--anchor-width)] max-w-80">
            <SelectGroup>
              {companyItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>

      <Field className="w-full gap-2 sm:w-40">
        <FieldLabel htmlFor="match-gap-seniority" className={CONTROL_LABEL_CLASS}>
          Seniority
        </FieldLabel>
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
            className="w-full bg-background"
            aria-label="Filter by seniority"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start" alignItemWithTrigger={false} className="w-max min-w-[var(--anchor-width)]">
            <SelectGroup>
              {seniorityItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>

      <Field className="w-full gap-2 sm:w-44">
        <FieldTitle className={CONTROL_LABEL_CLASS}>Stage</FieldTitle>
        <FacetPopover
          label="Stage"
          counts={{ ...Object.fromEntries(TARGET_STATUSES.map((s) => [s, 0])), ...statusCounts }}
          selected={value.statuses}
          onChange={(statuses) => onChange({ ...value, statuses })}
          getLabel={pipelineStageLabel}
          presentation="field"
        />
      </Field>

      <Field orientation="horizontal" className="h-9 w-auto gap-2 self-end">
        <Switch
          id="match-gap-gaps-only"
          checked={value.gapsOnly}
          onCheckedChange={(gapsOnly) => onChange({ ...value, gapsOnly })}
        />
        <FieldLabel htmlFor="match-gap-gaps-only" className="text-sm font-medium">
          Gaps only
        </FieldLabel>
      </Field>

      <Field className="w-auto gap-2">
        <FieldTitle className={CONTROL_LABEL_CLASS}>
          Weighting
        </FieldTitle>
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
      </Field>
    </FieldGroup>
  );
}
