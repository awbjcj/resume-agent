import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field";
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
  const companyItems = [
    { label: "All companies", value: ALL },
    ...companies.map((company) => ({ label: company, value: company })),
  ];
  const seniorityItems = [
    { label: "All levels", value: ALL },
    ...seniorities.map((seniority) => ({ label: seniority, value: seniority })),
  ];

  return (
    <FieldGroup className="flex-row flex-wrap items-end gap-4">
      <Field className="w-auto gap-1.5">
        <FieldLabel htmlFor="match-gap-company" className="text-xs text-muted-foreground">
          Company
        </FieldLabel>
        <Select
          items={companyItems}
          value={value.company ?? ALL}
          onValueChange={(company) =>
            onChange({ ...value, company: company === ALL ? null : company })
          }
        >
          <SelectTrigger id="match-gap-company" className="w-44" aria-label="Filter by company">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
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

      <Field className="w-auto gap-1.5">
        <FieldLabel htmlFor="match-gap-seniority" className="text-xs text-muted-foreground">
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
            className="w-40"
            aria-label="Filter by seniority"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
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

      <Field orientation="horizontal" className="h-8 w-auto">
        <Switch
          id="match-gap-gaps-only"
          checked={value.gapsOnly}
          onCheckedChange={(gapsOnly) => onChange({ ...value, gapsOnly })}
        />
        <FieldLabel htmlFor="match-gap-gaps-only">Gaps only</FieldLabel>
      </Field>

      <Field className="w-auto gap-1.5">
        <FieldTitle className="text-xs font-normal text-muted-foreground">
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
