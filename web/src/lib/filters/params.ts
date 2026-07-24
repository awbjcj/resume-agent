import type { FilterState } from "./types";

const SET_PARAM: [keyof FilterState, string][] = [
  ["source", "source"],
  ["status", "status"],
  ["remote", "remote"],
  ["sponsorship", "sponsorship"],
  ["seniority", "seniority"],
  ["employmentType", "employmentType"],
  ["industry", "industry"],
  ["country", "country"],
  ["region", "region"],
  ["city", "city"],
  ["companySize", "companySize"],
  ["skills", "skills"],
];

export function boardFilterToParams(
  s: FilterState,
  opts: { page?: number; pageSize?: number; archived?: boolean } = {},
): Record<string, string> {
  const p: Record<string, string> = { sortBy: s.sort, preset: s.preset };
  if (s.q.trim()) p.q = s.q.trim();
  if (s.rejectReason.trim()) p.rejectReason = s.rejectReason.trim();
  if (s.fitMin != null) p.minFit = String(s.fitMin);
  if (s.maxFit != null) p.maxFit = String(s.maxFit);
  if (s.salaryMin != null) p.minSalary = String(s.salaryMin);
  if (s.staleDays != null) p.staleDays = String(s.staleDays);
  if (s.staleMinDays != null) p.staleMinDays = String(s.staleMinDays);
  for (const [key, param] of SET_PARAM) {
    const set = s[key] as Set<string>;
    if (set.size) p[param] = [...set].join(",");
  }
  if (opts.page != null) p.page = String(opts.page);
  if (opts.pageSize != null) p.pageSize = String(opts.pageSize);
  if (opts.archived) p.archived = "true";
  return p;
}
