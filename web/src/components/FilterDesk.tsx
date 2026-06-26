import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { emptyFilterState, type FilterState, type Preset, type SortKey } from "@/lib/filters/types";
import { industryLabel } from "@/lib/filters/sic-labels";
import type { Facets } from "@/features/board/use-board-query";

import { ActiveFilterSummary } from "./filters/ActiveFilterSummary";
import { FacetPopover } from "./filters/FacetPopover";

const SORTS: [SortKey, string][] = [
  ["fit", "Fit"],
  ["salary", "Salary"],
  ["recency", "Recency"],
  ["composite", "Composite"],
  ["company", "Company"],
  ["stage", "Stage"],
];
const PRESETS: [Preset, string][] = [
  ["balanced", "Balanced"],
  ["pay_first", "Pay-first"],
  ["freshest", "Freshest"],
];

const REMOTE = ["remote", "hybrid", "onsite"];
const SPONSORSHIP = ["offered", "silent", "denied"];
const SENIORITY = ["junior", "mid", "senior", "staff", "principal"];
const EMPLOYMENT_TYPE = ["full_time", "contract", "internship", "part_time"];

// Every facet renders as the same compact active-filter popover. `options`
// seeds the canonical values for enumerated facets so they stay selectable even
// at zero count; `getLabel` resolves wire values to display names (industry
// codes → SIC labels).
type FacetSpec = {
  key: (typeof SET_KEYS)[number];
  label: string;
  options?: string[];
  getLabel?: (value: string) => string;
};

const SET_KEYS = [
  "source",
  "status",
  "remote",
  "sponsorship",
  "seniority",
  "employmentType",
  "industry",
  "country",
  "region",
  "city",
  "companySize",
  "skills",
] as const;

function countsWithSelected(counts: Record<string, number> | undefined, selected: Set<string>) {
  const next = { ...(counts ?? {}) };
  for (const value of selected) next[value] ??= 0;
  return next;
}

function hasOptions(counts: Record<string, number>, selected: Set<string>) {
  return Object.keys(counts).length > 0 || selected.size > 0;
}

function pretty(value: string) {
  return value.replace(/_/g, " ");
}

export function FilterDesk({
  filter,
  facets,
  total,
  onChange,
}: {
  filter: FilterState;
  facets: Facets;
  total: number;
  onChange: (s: FilterState) => void;
}) {
  const set = (patch: Partial<FilterState>) => onChange({ ...filter, ...patch });
  const setFacet = (key: (typeof SET_KEYS)[number], value: Set<string>) =>
    onChange({ ...filter, [key]: value });
  const removeFilter = (key: keyof FilterState, value: string) => {
    if ((SET_KEYS as readonly string[]).includes(key)) {
      const next = new Set(filter[key as (typeof SET_KEYS)[number]]);
      next.delete(value);
      set({ [key]: next } as Partial<FilterState>);
      return;
    }
    if (key === "q") set({ q: "" });
    else if (key === "fitMin") set({ fitMin: null });
    else if (key === "maxFit") set({ maxFit: null });
    else if (key === "salaryMin") set({ salaryMin: null });
    else if (key === "staleDays") set({ staleDays: null });
  };
  const clearFilters = () => {
    const cleared = emptyFilterState();
    cleared.sort = filter.sort;
    cleared.preset = filter.preset;
    onChange(cleared);
  };

  const facetSpecs: FacetSpec[] = [
    { key: "source", label: "Source" },
    { key: "status", label: "Status" },
    { key: "remote", label: "Remote", options: REMOTE },
    { key: "sponsorship", label: "Sponsorship", options: SPONSORSHIP },
    { key: "seniority", label: "Seniority", options: SENIORITY },
    { key: "employmentType", label: "Type", options: EMPLOYMENT_TYPE },
    { key: "industry", label: "Industry", getLabel: industryLabel },
    { key: "country", label: "Country" },
    { key: "region", label: "Region" },
    { key: "city", label: "City" },
    { key: "companySize", label: "Company size" },
    { key: "skills", label: "Skills" },
  ];

  return (
    <section
      aria-label="Filter and sort"
      className="mb-7 rounded-lg border bg-card p-5 shadow-[0_1px_2px_rgba(24,32,38,0.04)]"
    >
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Filter &amp; sort</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Server-filtered results with live facet counts.
          </p>
        </div>
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {total.toLocaleString()} matching
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-q" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Search
          </Label>
          <Input
            id="f-q"
            type="search"
            className="h-10 bg-card"
            value={filter.q}
            onChange={(event) => set({ q: event.target.value })}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-salary" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Min salary (USD)
          </Label>
          <Input
            id="f-salary"
            type="number"
            min={0}
            step={10000}
            className="h-10 bg-card"
            value={filter.salaryMin ?? ""}
            onChange={(event) => set({ salaryMin: Number(event.target.value) || null })}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="f-fit" className="text-xs font-semibold uppercase tracking-[0.14em]">
              Min fit
            </Label>
            <span className="text-xs tabular-nums text-muted-foreground">{filter.fitMin ?? 0}</span>
          </div>
          <Slider
            id="f-fit"
            aria-label="Min fit"
            min={0}
            max={100}
            step={1}
            value={[filter.fitMin ?? 0]}
            onValueChange={(value) => {
              const fit = (value as number[])[0] ?? 0;
              set({ fitMin: fit === 0 ? null : fit });
            }}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-sort" className="text-xs font-semibold uppercase tracking-[0.14em]">
            Sort by
          </Label>
          <Select value={filter.sort} onValueChange={(value) => set({ sort: value as SortKey })}>
            <SelectTrigger id="f-sort" className="h-10 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {filter.sort === "composite" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="f-preset" className="text-xs font-semibold uppercase tracking-[0.14em]">
              Preset
            </Label>
            <Select value={filter.preset} onValueChange={(value) => set({ preset: value as Preset })}>
              <SelectTrigger id="f-preset" className="h-10 w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map(([key, label]) => (
                  <SelectItem key={key} value={key}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {facetSpecs.map(({ key, label, options, getLabel }) => {
          const counts = countsWithSelected(facets[key], filter[key]);
          for (const option of options ?? []) counts[option] ??= 0;
          if (!hasOptions(counts, filter[key])) return null;
          return (
            <FacetPopover
              key={key}
              label={label}
              counts={counts}
              selected={filter[key]}
              onChange={(next) => setFacet(key, next)}
              getLabel={getLabel ?? pretty}
            />
          );
        })}
      </div>

      <ActiveFilterSummary
        filter={filter}
        total={total}
        onRemove={removeFilter}
        onClear={clearFilters}
      />
    </section>
  );
}
