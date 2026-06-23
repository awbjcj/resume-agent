// Per-job display formatters, ported from the Streamlit dashboard's
// salary_label / meta_line helpers so the React card + modal show the same
// compact, null-omitting meta the old dashboard did.

export function salaryLabel(
  min: number | null | undefined,
  max: number | null | undefined,
  currency?: string | null,
): string | null {
  if (min == null && max == null) return null;
  const sym = currencySymbol(currency);
  const lo = min != null ? `${Math.round(min / 1000)}k` : null;
  const hi = max != null ? `${Math.round(max / 1000)}k` : null;
  if (lo && hi) return `${sym}${lo}–${hi}`;
  return `${sym}${lo ?? hi}`;
}

function currencySymbol(currency?: string | null): string {
  switch ((currency ?? "USD").toUpperCase()) {
    case "USD":
    case "CAD":
    case "AUD":
      return "$";
    case "EUR":
      return "€";
    case "GBP":
      return "£";
    default:
      return "";
  }
}

export function recency(postedAt: string | null | undefined): string | null {
  if (!postedAt) return null;
  const posted = new Date(postedAt);
  if (Number.isNaN(posted.getTime())) return null;
  const days = Math.max(0, Math.floor((Date.now() - posted.getTime()) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? "1mo ago" : `${months}mo ago`;
}

/** One compact line: salary · seniority · type · industry · recency. */
export function metaLine(row: {
  salaryMin?: number | null;
  salaryMax?: number | null;
  salaryCurrency?: string | null;
  seniority?: string | null;
  employmentType?: string | null;
  industry?: string | null;
  postedAt?: string | null;
}): string[] {
  return [
    salaryLabel(row.salaryMin, row.salaryMax, row.salaryCurrency),
    row.seniority,
    row.employmentType,
    row.industry,
    recency(row.postedAt),
  ].filter((p): p is string => Boolean(p));
}
