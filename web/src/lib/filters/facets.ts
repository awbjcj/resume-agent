import { normalizeSkill } from "./normalize";
import type { ShortlistItem, SkillTag } from "./types";

const uniqueSorted = (values: (string | null | undefined)[]): string[] =>
  [...new Set(values.filter((value): value is string => Boolean(value)))].sort();

export function availableCountries(rows: ShortlistItem[]): string[] {
  return uniqueSorted(rows.map((row) => row.locationCountry));
}

export function availableStates(rows: ShortlistItem[], countries: Set<string>): string[] {
  return uniqueSorted(
    rows
      .filter((row) => !countries.size || (row.locationCountry && countries.has(row.locationCountry)))
      .map((row) => row.locationRegion),
  );
}

export function availableCities(
  rows: ShortlistItem[],
  countries: Set<string>,
  states: Set<string>,
): string[] {
  return uniqueSorted(
    rows
      .filter((row) => !countries.size || (row.locationCountry && countries.has(row.locationCountry)))
      .filter((row) => !states.size || (row.locationRegion && states.has(row.locationRegion)))
      .map((row) => row.locationCity),
  );
}

export function availableIndustries(rows: ShortlistItem[]): [string, [string, string][]][] {
  const byDivision = new Map<string, Set<string>>();

  for (const row of rows) {
    if (row.sicMajor && row.sicDivision && row.sicLabel) {
      const codes = byDivision.get(row.sicDivision) ?? new Set<string>();
      codes.add(JSON.stringify([row.sicMajor, row.sicLabel]));
      byDivision.set(row.sicDivision, codes);
    }
  }

  return [...byDivision.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([division, codes]) => [
      division,
      [...codes]
        .map((serialized) => JSON.parse(serialized) as [string, string])
        .sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1])),
    ]);
}

export function availableSkillCloud(rows: ShortlistItem[]): SkillTag[] {
  const merged = new Map<string, SkillTag>();

  for (const row of rows) {
    for (const tag of row.skills) {
      const token = normalizeSkill(tag.name);
      if (!token) {
        continue;
      }

      const existing = merged.get(token);
      if (!existing) {
        merged.set(token, { ...tag });
      } else {
        existing.covered = existing.covered || tag.covered;
        existing.required = existing.required || tag.required;
      }
    }
  }

  return [...merged.values()].sort((a, b) => {
    const aCoveredRank = a.covered ? 0 : 1;
    const bCoveredRank = b.covered ? 0 : 1;
    return aCoveredRank - bCoveredRank || a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  });
}
