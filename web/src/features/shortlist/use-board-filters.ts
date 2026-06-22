import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { emptyFilterState, type FilterState, type Preset, type SortKey } from "@/lib/filters/types";

const SET_KEYS = [
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

export function stateToParams(s: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (s.salaryMin != null) p.set("salaryMin", String(s.salaryMin));
  if (s.fitMin != null) p.set("fitMin", String(s.fitMin));
  if (s.sort !== "fit") p.set("sort", s.sort);
  if (s.preset !== "balanced") p.set("preset", s.preset);
  for (const k of SET_KEYS) {
    const set = s[k];
    if (set.size) p.set(k, [...set].join(","));
  }
  return p;
}

export function paramsToState(p: URLSearchParams): FilterState {
  const s = emptyFilterState();
  const salary = p.get("salaryMin");
  const fit = p.get("fitMin");
  if (salary) s.salaryMin = Number(salary);
  if (fit) s.fitMin = Number(fit);
  if (p.get("sort")) s.sort = p.get("sort") as SortKey;
  if (p.get("preset")) s.preset = p.get("preset") as Preset;
  for (const k of SET_KEYS) {
    const raw = p.get(k);
    if (raw) s[k] = new Set(raw.split(","));
  }
  return s;
}

export function useBoardFilters(): [FilterState, (s: FilterState) => void] {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => paramsToState(params), [params]);
  return [state, (s) => setParams(stateToParams(s), { replace: true })];
}
