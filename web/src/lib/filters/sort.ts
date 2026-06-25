import type { FilterState, Preset, ShortlistItem } from "./types";

const SALARY_CEILING = 250_000;
const RECENCY_WINDOW_DAYS = 30;
const NEUTRAL = 50;
const MS_PER_DAY = 86_400_000;

const PRESETS: Record<Preset, [number, number, number]> = {
  balanced: [0.5, 0.3, 0.2],
  pay_first: [0.3, 0.55, 0.15],
  freshest: [0.35, 0.2, 0.45],
};

function salaryValue(row: ShortlistItem): number | null {
  return row.salaryMax ?? row.salaryMin;
}

function ageDays(row: ShortlistItem, now: Date): number | null {
  if (!row.postedAt) {
    return null;
  }
  return (now.getTime() - new Date(row.postedAt).getTime()) / MS_PER_DAY;
}

function compositeRaw(row: ShortlistItem, preset: Preset, now: Date): number {
  const [wFit, wSalary, wRecency] = PRESETS[preset] ?? PRESETS.balanced;
  const fitN = row.fitScore ?? NEUTRAL;

  const salary = salaryValue(row);
  const salaryN =
    salary !== null ? (Math.min(salary, SALARY_CEILING) / SALARY_CEILING) * 100 : NEUTRAL;

  const age = ageDays(row, now);
  const recencyN =
    age !== null
      ? Math.min(100, Math.max(0, 100 - (age / RECENCY_WINDOW_DAYS) * 100))
      : NEUTRAL;

  return wFit * fitN + wSalary * salaryN + wRecency * recencyN;
}

export function compositeScore(row: ShortlistItem, preset: Preset, now: Date): number {
  // Display value. Ordering uses the raw score (see compositeRaw).
  return Math.round(compositeRaw(row, preset, now) * 10000) / 10000;
}

export function sortRows(
  rows: ShortlistItem[],
  state: FilterState,
  now: Date = new Date(),
): ShortlistItem[] {
  const arr = [...rows];

  if (state.sort === "salary") {
    return arr.sort((a, b) => {
      const av = salaryValue(a);
      const bv = salaryValue(b);
      return Number(bv !== null) - Number(av !== null) || (bv ?? 0) - (av ?? 0);
    });
  }

  if (state.sort === "recency") {
    return arr.sort((a, b) => {
      const aa = ageDays(a, now);
      const ba = ageDays(b, now);
      return (
        Number(Boolean(b.postedAt)) - Number(Boolean(a.postedAt)) ||
        Number(ba !== null) - Number(aa !== null) ||
        (aa ?? 0) - (ba ?? 0)
      );
    });
  }

  if (state.sort === "composite") {
    return arr.sort(
      (a, b) => compositeRaw(b, state.preset, now) - compositeRaw(a, state.preset, now),
    );
  }

  return arr.sort((a, b) => {
    return (
      Number(b.fitScore !== null) - Number(a.fitScore !== null) ||
      (b.fitScore ?? 0) - (a.fitScore ?? 0)
    );
  });
}
