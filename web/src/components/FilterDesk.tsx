import { useMemo } from "react";

import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "./MultiSelect";
import {
  availableCities,
  availableCountries,
  availableIndustries,
  availableSkillCloud,
  availableStates,
} from "@/lib/filters/facets";
import { normalizeSkill } from "@/lib/filters/normalize";
import type { FilterState, Preset, ShortlistItem, SortKey } from "@/lib/filters/types";

const SORTS: [SortKey, string][] = [
  ["fit", "Fit"],
  ["salary", "Salary"],
  ["recency", "Recency"],
  ["composite", "Composite"],
];
const PRESETS: [Preset, string][] = [
  ["balanced", "Balanced"],
  ["pay_first", "Pay-first"],
  ["freshest", "Freshest"],
];

export function FilterDesk({
  rows,
  state,
  onChange,
}: {
  rows: ShortlistItem[];
  state: FilterState;
  onChange: (s: FilterState) => void;
}) {
  const set = (patch: Partial<FilterState>) => onChange({ ...state, ...patch });

  const countries = useMemo(() => availableCountries(rows), [rows]);
  const states = useMemo(() => availableStates(rows, state.country), [rows, state.country]);
  const cities = useMemo(
    () => availableCities(rows, state.country, state.region),
    [rows, state.country, state.region],
  );
  const industries = useMemo(() => availableIndustries(rows), [rows]);
  const skills = useMemo(() => availableSkillCloud(rows), [rows]);
  const sizes = useMemo(
    () => [...new Set(rows.map((r) => r.companySize).filter(Boolean) as string[])].sort(),
    [rows],
  );

  // Flatten SIC [division, [[code,label],...]] to a single code list + label map.
  const sicCodes: string[] = [];
  const sicLabels: Record<string, string> = {};
  for (const [, codes] of industries) {
    for (const [code, label] of codes) {
      if (!(code in sicLabels)) {
        sicCodes.push(code);
        sicLabels[code] = label;
      }
    }
  }

  return (
    <section
      aria-label="Filter and sort"
      className="mb-6 rounded-lg border bg-card p-4"
    >
      <div className="mb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Filter &amp; sort
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-salary">Min salary (USD)</Label>
          <Input
            id="f-salary"
            type="number"
            min={0}
            step={10000}
            value={state.salaryMin ?? 0}
            onChange={(e) => set({ salaryMin: Number(e.target.value) || null })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-fit">Min fit</Label>
          <Slider
            id="f-fit"
            aria-label="Min fit"
            min={0}
            max={100}
            step={1}
            value={[state.fitMin ?? 0]}
            onValueChange={(v) => set({ fitMin: (v as number[])[0] || null })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="f-sort">Sort by</Label>
          <Select value={state.sort} onValueChange={(v) => set({ sort: v as SortKey })}>
            <SelectTrigger id="f-sort" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map(([k, l]) => (
                <SelectItem key={k} value={k}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <MultiSelect
          label="Company size"
          options={sizes}
          selected={state.companySize}
          onChange={(s) => set({ companySize: s })}
        />

        <MultiSelect
          label="Remote"
          options={["remote", "hybrid", "onsite"]}
          selected={state.remote}
          onChange={(s) => set({ remote: s })}
        />
        <MultiSelect
          label="Sponsorship"
          options={["offered", "silent", "denied"]}
          selected={state.sponsorship}
          onChange={(s) => set({ sponsorship: s })}
        />
        <MultiSelect
          label="Seniority"
          options={["junior", "mid", "senior", "staff", "principal"]}
          selected={state.seniority}
          onChange={(s) => set({ seniority: s })}
        />
        <MultiSelect
          label="Type"
          options={["full_time", "contract", "internship", "part_time"]}
          selected={state.employmentType}
          onChange={(s) => set({ employmentType: s })}
        />

        <MultiSelect
          label="Country"
          options={countries}
          selected={state.country}
          onChange={(s) => set({ country: s })}
        />
        <MultiSelect
          label="State (US)"
          options={states}
          selected={state.region}
          onChange={(s) => set({ region: s })}
        />
        <MultiSelect
          label="City"
          options={cities}
          selected={state.city}
          onChange={(s) => set({ city: s })}
        />
        <MultiSelect
          label="Industry"
          options={sicCodes}
          getLabel={(c) => sicLabels[c] ?? c}
          selected={state.industry}
          onChange={(s) => set({ industry: s })}
        />

        <MultiSelect
          label="Skills (any match)"
          options={skills.map((t) => t.name)}
          selected={new Set([...state.skills])}
          onChange={(picked) => set({ skills: new Set([...picked].map(normalizeSkill)) })}
        />
        {state.sort === "composite" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="f-preset">Preset</Label>
            <Select value={state.preset} onValueChange={(v) => set({ preset: v as Preset })}>
              <SelectTrigger id="f-preset" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map(([k, l]) => (
                  <SelectItem key={k} value={k}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </section>
  );
}
