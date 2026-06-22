import { normalizeSkill } from "./normalize";
import type { FilterState, ShortlistItem } from "./types";

function passes(row: ShortlistItem, state: FilterState): boolean {
  if (state.salaryMin !== null && row.salaryMax !== null) {
    const currency = (row.salaryCurrency ?? "USD").toUpperCase();
    if (currency === "USD" && row.salaryMax < state.salaryMin) {
      return false;
    }
  }

  if (state.fitMin !== null && row.fitScore !== null && row.fitScore < state.fitMin) {
    return false;
  }

  const facets: [Set<string>, string | null | undefined][] = [
    [state.remote, row.remotePolicy],
    [state.sponsorship, row.sponsorshipSignal],
    [state.seniority, row.seniority],
    [state.employmentType, row.employmentType],
    [state.industry, row.sicMajor],
    [state.country, row.locationCountry],
    [state.region, row.locationRegion],
    [state.city, row.locationCity],
    [state.companySize, row.companySize],
  ];

  for (const [selected, value] of facets) {
    if (selected.size && value !== null && value !== undefined && !selected.has(value)) {
      return false;
    }
  }

  if (state.skills.size) {
    const rowTokens = new Set(row.skills.map((tag) => normalizeSkill(tag.name)));
    let hasOverlap = false;
    for (const token of state.skills) {
      if (rowTokens.has(token)) {
        hasOverlap = true;
        break;
      }
    }
    if (!hasOverlap) {
      return false;
    }
  }

  return true;
}

export function applyFilters(
  rows: ShortlistItem[],
  state: FilterState,
): ShortlistItem[] {
  return rows.filter((row) => passes(row, state));
}
