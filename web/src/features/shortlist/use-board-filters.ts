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

export function stateToParams(
  s: FilterState,
  defaultSort: SortKey = "fit",
): URLSearchParams {
  const p = new URLSearchParams();
  if (s.q.trim()) p.set("q", s.q.trim());
  if (s.rejectReason.trim()) p.set("rejectReason", s.rejectReason.trim());
  if (s.salaryMin != null) p.set("salaryMin", String(s.salaryMin));
  if (s.fitMin != null) p.set("fitMin", String(s.fitMin));
  if (s.maxFit != null) p.set("maxFit", String(s.maxFit));
  if (s.staleDays != null) p.set("staleDays", String(s.staleDays));
  if (s.staleMinDays != null) p.set("staleMinDays", String(s.staleMinDays));
  if (s.sort !== defaultSort) p.set("sort", s.sort);
  if (s.preset !== "balanced") p.set("preset", s.preset);
  for (const k of SET_KEYS) {
    const set = s[k];
    if (set.size) p.set(k, [...set].join(","));
  }
  return p;
}

export function paramsToState(
  p: URLSearchParams,
  defaultSort: SortKey = "fit",
): FilterState {
  const s = emptyFilterState();
  s.sort = defaultSort;
  const q = p.get("q");
  if (q) s.q = q;
  const rejectReason = p.get("rejectReason");
  if (rejectReason) s.rejectReason = rejectReason;
  s.salaryMin = parsePositiveNumber(p.get("salaryMin"));
  s.fitMin = parsePositiveNumber(p.get("fitMin"));
  s.maxFit = parsePositiveNumber(p.get("maxFit"));
  s.staleDays = parsePositiveNumber(p.get("staleDays"));
  s.staleMinDays = parsePositiveNumber(p.get("staleMinDays"));
  if (p.get("sort")) s.sort = p.get("sort") as SortKey;
  if (p.get("preset")) s.preset = p.get("preset") as Preset;
  for (const k of SET_KEYS) {
    const raw = p.get(k);
    if (raw) s[k] = new Set(raw.split(","));
  }
  return s;
}

export function useBoardFilters(
  defaultSort: SortKey = "fit",
): [FilterState, (s: FilterState) => void] {
  const [params, setParams] = useSearchParams();
  const state = useMemo(
    () => paramsToState(params, defaultSort),
    [params, defaultSort],
  );
  return [
    state,
    (s) => setParams(stateToParams(s, defaultSort), { replace: true }),
  ];
}
