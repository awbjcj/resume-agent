import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { emptyFilterState, type FilterState, type Preset, type SortKey } from "@/lib/filters/types";

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

function parsePositiveNumber(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function stateToParams(s: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (s.q.trim()) p.set("q", s.q.trim());
  if (s.salaryMin != null) p.set("salaryMin", String(s.salaryMin));
  if (s.fitMin != null) p.set("fitMin", String(s.fitMin));
  if (s.maxFit != null) p.set("maxFit", String(s.maxFit));
  if (s.staleDays != null) p.set("staleDays", String(s.staleDays));
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
  const q = p.get("q");
  if (q) s.q = q;
  s.salaryMin = parsePositiveNumber(p.get("salaryMin"));
  s.fitMin = parsePositiveNumber(p.get("fitMin"));
  s.maxFit = parsePositiveNumber(p.get("maxFit"));
  s.staleDays = parsePositiveNumber(p.get("staleDays"));
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
