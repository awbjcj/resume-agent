import { SearchIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

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
import { fieldLabel } from "@/lib/format";
import { industryLabel } from "@/lib/filters/industry-label";
import {
  emptyFilterState,
  type FilterState,
  type Preset,
  type SortKey,
} from "@/lib/filters/types";

import { ActiveFilterSummary } from "./filters/ActiveFilterSummary";
import { FacetPopover } from "./filters/FacetPopover";

const SORTS: readonly SortKey[] = ["fit", "salary", "recency", "composite", "company"];
const SORT_LABEL_KEYS = {
  fit: "filters.sortOptions.fit",
  salary: "filters.sortOptions.salary",
  recency: "filters.sortOptions.recency",
  composite: "filters.sortOptions.composite",
  company: "filters.sortOptions.company",
} as const;
const PRESETS: readonly Preset[] = ["balanced", "pay_first", "freshest"];
const PRESET_LABEL_KEYS = {
  balanced: "filters.presets.balanced",
  pay_first: "filters.presets.payFirst",
  freshest: "filters.presets.freshest",
} as const;
const STALE_DAYS = [7, 14, 30, 45, 90] as const;
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

// Default facet label: underscore-to-space only, no case changes. Facets
// whose canonical values are job-brief enums (source, remote, sponsorship,
// seniority, type, company size, industry) opt into `fieldLabel`'s title
// casing explicitly below; free-text facets like skills, country, region,
// and city keep their own canonical casing untouched.
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
  const { t } = useTranslation();
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
    else if (key === "rejectReason") set({ rejectReason: "" });
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
  const sortItems = SORTS.map((value) => ({
    value,
    label: t(SORT_LABEL_KEYS[value]),
  }));
  const presetItems = PRESETS.map((value) => ({
    value,
    label: t(PRESET_LABEL_KEYS[value]),
  }));
  const staleItems = [
    { value: "any", label: t("filters.posted.anyTime") },
    ...STALE_DAYS.map((days) => ({
      value: String(days),
      label: t("filters.posted.withinDays", { count: days }),
    })),
  ];

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
    { key: "source", label: "Source", getLabel: fieldLabel },
    { key: "remote", label: "Remote", options: REMOTE, getLabel: fieldLabel },
    { key: "sponsorship", label: "Sponsorship", options: SPONSORSHIP, getLabel: fieldLabel },
    { key: "seniority", label: "Seniority", options: SENIORITY, getLabel: fieldLabel },
    { key: "employmentType", label: "Type", options: EMPLOYMENT_TYPE, getLabel: fieldLabel },
    { key: "industry", label: "Industry", getLabel: industryLabel },
    { key: "country", label: "Country" },
    { key: "region", label: "Region" },
    { key: "city", label: "City" },
    { key: "companySize", label: "Company size", getLabel: fieldLabel },
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

          <div className="flex w-full flex-col gap-2 sm:flex-row lg:min-w-[28rem] lg:flex-1">
            <Field className="w-full gap-1.5 sm:basis-0 sm:flex-1">
              <FieldLabel htmlFor="f-q" className={CONTROL_LABEL_CLASS}>
                Search
              </FieldLabel>
              <div className="relative">
                <SearchIcon
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  id="f-q"
                  type="search"
                  placeholder="Title, company, skill…"
                  className="h-9 bg-background pl-8"
                  value={draft.q}
                  onChange={(event) =>
                    setPrimaryDraft({ ...draft, q: event.target.value })
                  }
                />
              </div>
            </Field>

            <MinFitInput
              id="f-fit"
              value={draft.fitMin}
              onChange={(fitMin) => setPrimaryDraft({ ...draft, fitMin })}
            />
          </div>

          <SalaryThresholdInput
            id="f-salary"
            value={draft.salaryMin}
            valid={salaryDraft.valid}
            onChange={(salaryMin) => setPrimaryDraft({ ...draft, salaryMin })}
          />

          <Field className="w-full gap-1.5 sm:w-30">
            <FieldLabel htmlFor="f-stale" className={CONTROL_LABEL_CLASS}>
              {t("filters.posted.label")}
            </FieldLabel>
            <Select
              items={staleItems}
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
                  {staleItems.map((item) => (
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
              {t("filters.sortBy")}
            </FieldLabel>
            <Select
              items={sortItems}
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
                  {sortItems.map((item) => (
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
                {t("filters.preset")}
              </FieldLabel>
              <Select
                items={presetItems}
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
                    {presetItems.map((item) => (
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
