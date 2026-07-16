import { SearchIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { MinFitInput } from "@/components/MinFitInput";
import { SalaryThresholdInput } from "@/components/SalaryThresholdInput";
import { Button } from "@/components/ui/button";
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
import type { Facets } from "@/features/board/use-board-query";
import { industryLabel } from "@/lib/filters/industry-label";
import {
  emptyFilterState,
  type FilterState,
  type Preset,
  type SortKey,
} from "@/lib/filters/types";

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
const STALE_OPTIONS: [string, string][] = [
  ["any", "Any time"],
  ["7", "≤ 7 days"],
  ["14", "≤ 14 days"],
  ["30", "≤ 30 days"],
  ["45", "≤ 45 days"],
  ["90", "≤ 90 days"],
];

const SORT_ITEMS = SORTS.map(([value, label]) => ({ value, label }));
const PRESET_ITEMS = PRESETS.map(([value, label]) => ({ value, label }));
const STALE_ITEMS = STALE_OPTIONS.map(([value, label]) => ({ value, label }));
const CONTROL_LABEL_CLASS =
  "text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground";

const REMOTE = ["remote", "hybrid", "onsite"];
const SPONSORSHIP = ["offered", "silent", "denied"];
const SENIORITY = ["junior", "mid", "senior", "staff", "principal"];
const EMPLOYMENT_TYPE = ["full_time", "contract", "internship", "part_time"];

// Every facet renders as the same compact active-filter popover. `options`
// seeds the canonical values for enumerated facets so they stay selectable even
// at zero count; `getLabel` resolves wire values to readable display names.
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

function countsWithSelected(
  counts: Record<string, number> | undefined,
  selected: Set<string>,
) {
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

function salaryInputValue(value: number | null) {
  return value == null ? "" : String(value);
}

function parseSalaryInput(value: string): {
  value: number | null;
  valid: boolean;
} {
  const trimmed = value.trim();
  if (!trimmed) return { value: null, valid: true };

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0)
    return { value: null, valid: false };
  return { value: parsed === 0 ? null : Math.round(parsed), valid: true };
}

function normalizeFitInput(value: number) {
  const fit = Math.min(100, Math.max(0, Math.round(value)));
  return fit === 0 ? null : fit;
}

type PrimaryFilterDraft = {
  sourceQ: string;
  sourceSalaryMin: number | null;
  sourceFitMin: number | null;
  q: string;
  salaryMin: string;
  fitMin: number;
};

function primaryDraftFromFilter(filter: FilterState): PrimaryFilterDraft {
  return {
    sourceQ: filter.q,
    sourceSalaryMin: filter.salaryMin,
    sourceFitMin: filter.fitMin,
    q: filter.q,
    salaryMin: salaryInputValue(filter.salaryMin),
    fitMin: filter.fitMin ?? 0,
  };
}

function isPrimaryDraftCurrent(draft: PrimaryFilterDraft, filter: FilterState) {
  return (
    draft.sourceQ === filter.q &&
    draft.sourceSalaryMin === filter.salaryMin &&
    draft.sourceFitMin === filter.fitMin
  );
}

export function FilterDesk({
  filter,
  facets,
  total,
  onChange,
  statusOptions,
  statusLabel,
}: {
  filter: FilterState;
  facets: Facets;
  total: number;
  onChange: (s: FilterState) => void;
  /** Canonical status/stage values to keep selectable even at zero count (e.g. pipeline stages). */
  statusOptions?: readonly string[];
  /** Display formatter for status/stage values. Defaults to underscore-stripping. */
  statusLabel?: (value: string) => string;
}) {
  const [primaryDraft, setPrimaryDraft] = useState(() =>
    primaryDraftFromFilter(filter),
  );
  const [openFacet, setOpenFacet] = useState<(typeof SET_KEYS)[number] | null>(
    null,
  );
  const draft = isPrimaryDraftCurrent(primaryDraft, filter)
    ? primaryDraft
    : primaryDraftFromFilter(filter);
  const set = (patch: Partial<FilterState>) =>
    onChange({ ...filter, ...patch });
  const setFacet = (key: (typeof SET_KEYS)[number], value: Set<string>) =>
    onChange({ ...filter, [key]: value });
  const handleFacetOpenChange = (
    key: (typeof SET_KEYS)[number],
    nextOpen: boolean,
  ) =>
    setOpenFacet((current) =>
      nextOpen ? key : current === key ? null : current,
    );
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
    else if (key === "staleMinDays") set({ staleMinDays: null });
  };
  const clearFilters = () => {
    const cleared = emptyFilterState();
    cleared.sort = filter.sort;
    cleared.preset = filter.preset;
    onChange(cleared);
  };

  const salaryDraft = useMemo(
    () => parseSalaryInput(draft.salaryMin),
    [draft.salaryMin],
  );
  const committedQ = draft.q.trim();
  const committedFitMin = normalizeFitInput(draft.fitMin);
  const hasPrimaryDraftChanges =
    committedQ !== filter.q.trim() ||
    salaryDraft.value !== filter.salaryMin ||
    committedFitMin !== filter.fitMin;

  const applyPrimaryFilters = () => {
    if (!salaryDraft.valid || !hasPrimaryDraftChanges) return;
    set({
      q: committedQ,
      salaryMin: salaryDraft.value,
      fitMin: committedFitMin,
    });
    setPrimaryDraft({
      sourceQ: committedQ,
      sourceSalaryMin: salaryDraft.value,
      sourceFitMin: committedFitMin,
      q: committedQ,
      salaryMin: salaryInputValue(salaryDraft.value),
      fitMin: committedFitMin ?? 0,
    });
  };

  const facetSpecs: FacetSpec[] = [
    { key: "source", label: "Source" },
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
  const statusCounts = countsWithSelected(facets.status, filter.status);
  for (const option of statusOptions ?? []) statusCounts[option] ??= 0;
  const showStatus = hasOptions(statusCounts, filter.status);
  const isOpenFacetRenderable =
    openFacet === null ||
    (openFacet === "status"
      ? showStatus
      : facetSpecs.some(({ key, options }) => {
          if (key !== openFacet) return false;
          const counts = countsWithSelected(facets[key], filter[key]);
          for (const option of options ?? []) counts[option] ??= 0;
          return hasOptions(counts, filter[key]);
        }));

  useEffect(() => {
    if (!isOpenFacetRenderable) {
      // A vanished server facet starts a fresh popover session if it returns.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOpenFacet(null);
    }
  }, [isOpenFacetRenderable]);

  return (
    <section
      aria-label="Filter and sort"
      className="mb-6 rounded-lg border bg-card p-4"
    >
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm font-semibold">Filter &amp; sort</span>
        <span className="text-xs font-semibold tabular-nums text-muted-foreground">
          {total.toLocaleString()} matching
        </span>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          applyPrimaryFilters();
        }}
      >
        <FieldGroup className="flex-row flex-wrap items-end gap-2">
          {showStatus && (
            <Field className="w-full gap-1.5 sm:w-30">
              <FieldTitle className={CONTROL_LABEL_CLASS}>Status</FieldTitle>
              <FacetPopover
                label="Status"
                counts={statusCounts}
                selected={filter.status}
                onChange={(next) => setFacet("status", next)}
                open={openFacet === "status"}
                onOpenChange={(nextOpen) =>
                  handleFacetOpenChange("status", nextOpen)
                }
                getLabel={statusLabel ?? pretty}
                presentation="field"
              />
            </Field>
          )}

          <Field className="w-full gap-1.5 sm:w-auto sm:min-w-56 sm:flex-1">
            <FieldLabel htmlFor="f-q" className={CONTROL_LABEL_CLASS}>
              Search
            </FieldLabel>
            <Input
              id="f-q"
              type="search"
              placeholder="Title, company, skill…"
              className="h-9 bg-background"
              value={draft.q}
              onChange={(event) =>
                setPrimaryDraft({ ...draft, q: event.target.value })
              }
            />
          </Field>

          <MinFitInput
            id="f-fit"
            value={draft.fitMin}
            onChange={(fitMin) => setPrimaryDraft({ ...draft, fitMin })}
          />

          <SalaryThresholdInput
            id="f-salary"
            value={draft.salaryMin}
            valid={salaryDraft.valid}
            onChange={(salaryMin) => setPrimaryDraft({ ...draft, salaryMin })}
          />

          <Field className="w-full gap-1.5 sm:w-30">
            <FieldLabel htmlFor="f-stale" className={CONTROL_LABEL_CLASS}>
              Posted
            </FieldLabel>
            <Select
              items={STALE_ITEMS}
              value={
                filter.staleDays == null ? "any" : String(filter.staleDays)
              }
              onValueChange={(value) =>
                set({ staleDays: value === "any" ? null : Number(value) })
              }
            >
              <SelectTrigger
                id="f-stale"
                size="compact"
                className="w-full bg-background"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent
                align="start"
                alignItemWithTrigger={false}
                className="w-max min-w-[var(--anchor-width)]"
              >
                <SelectGroup>
                  {STALE_ITEMS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>

          <Field className="w-full gap-1.5 sm:w-28">
            <FieldLabel htmlFor="f-sort" className={CONTROL_LABEL_CLASS}>
              Sort
            </FieldLabel>
            <Select
              items={SORT_ITEMS}
              value={filter.sort}
              onValueChange={(value) => set({ sort: value as SortKey })}
            >
              <SelectTrigger
                id="f-sort"
                size="compact"
                className="w-full bg-background"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent
                align="start"
                alignItemWithTrigger={false}
                className="w-max min-w-[var(--anchor-width)]"
              >
                <SelectGroup>
                  {SORT_ITEMS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>

          {filter.sort === "composite" && (
            <Field className="w-full gap-1.5 sm:w-28">
              <FieldLabel htmlFor="f-preset" className={CONTROL_LABEL_CLASS}>
                Preset
              </FieldLabel>
              <Select
                items={PRESET_ITEMS}
                value={filter.preset}
                onValueChange={(value) => set({ preset: value as Preset })}
              >
                <SelectTrigger
                  id="f-preset"
                  size="compact"
                  className="w-full bg-background"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  align="start"
                  alignItemWithTrigger={false}
                  className="w-max min-w-[var(--anchor-width)]"
                >
                  <SelectGroup>
                    {PRESET_ITEMS.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          )}

          <Button
            type="submit"
            size="sm"
            className="w-full sm:ml-auto sm:w-auto"
            disabled={!hasPrimaryDraftChanges || !salaryDraft.valid}
          >
            <SearchIcon data-icon="inline-start" />
            Apply
          </Button>
        </FieldGroup>
      </form>

      <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
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
              open={openFacet === key}
              onOpenChange={(nextOpen) => handleFacetOpenChange(key, nextOpen)}
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
