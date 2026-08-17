// Per-job display formatters shared by the React card and modal.

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

// Words that stay lowercase mid-phrase when title-casing a raw location string
// (e.g. "United States of America" -> "of" stays lowercase, not "Of").
const LOWERCASE_LOCATION_WORDS = new Set(["of", "the", "and", "de", "la", "van", "von"]);

function titleCaseWord(word: string): string {
  return word
    .split(/([-()[\]'])/)
    .map((part) => (/^[-()[\]']$/.test(part) || !part ? part : part[0].toUpperCase() + part.slice(1).toLowerCase()))
    .join("");
}

function titleCase(text: string): string {
  return text
    .trim()
    .split(/\s+/)
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (i > 0 && LOWERCASE_LOCATION_WORDS.has(lower)) return lower;
      return titleCaseWord(word);
    })
    .join(" ");
}

/** A bare 2-3 letter alpha token reads as a code (country/state abbreviation, e.g.
 * "US", "IE", "NY") and is uppercased; anything longer is title-cased so a
 * source that shouts "CALIFORNIA" renders as "California". */
function formatLocationSegment(segment: string): string {
  const trimmed = segment.trim();
  if (!trimmed) return "";
  if (/^[a-z]{2,3}$/i.test(trimmed)) return trimmed.toUpperCase();
  // Sources commonly write remote locations as "Remote - us". Keep the
  // descriptive part readable while treating the trailing token as a code.
  const trailingCode = /^(.*?)(\s[-–]\s)([a-z]{2,3})$/i.exec(trimmed);
  if (trailingCode) {
    return `${titleCase(trailingCode[1])}${trailingCode[2]}${trailingCode[3].toUpperCase()}`;
  }
  return titleCase(trimmed);
}

/** Normalizes a raw, un-structured location string ("san francisco, CALIFORNIA,
 * us") into consistent casing ("San Francisco, CALIFORNIA" -> "San Francisco,
 * California, US"). */
export function formatLocationText(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const formatted = raw
    .split(",")
    .map(formatLocationSegment)
    .filter(Boolean)
    .join(", ");
  return formatted || null;
}

type LocationInstance = {
  city?: string | null;
  region?: string | null;
  country?: string | null;
  raw?: string | null;
};

function instanceLabel(location: LocationInstance): string | null {
  if (location.raw && /\bremote\b/i.test(location.raw)) {
    return formatLocationText(location.raw);
  }
  const structured = [location.city, location.region, location.country]
    .filter(Boolean)
    .map((part) => formatLocationSegment(part!))
    .join(", ");
  return structured || formatLocationText(location.raw);
}

function joinLocationLabels(labels: Array<string | null>): string | null {
  const seen = new Set<string>();
  const values = labels.filter((label): label is string => {
    if (!label) return false;
    const key = label.toLocaleLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return values.length ? values.join(" | ") : null;
}

function compositeLocationLabel(raw: string): string | null {
  return joinLocationLabels(
    raw.split(/\s*(?:\||;)\s*/).map((value) => formatLocationText(value)),
  );
}

/** The single source of truth for how a job's location renders anywhere in the
 * UI. A normalized city/region/country tuple cannot represent multiple
 * alternatives, so preserve a provider's composite value; otherwise prefer
 * the normalized facets and fall back to the raw scraped string. */
export function locationLabel(job: {
  location?: string | null;
  locations?: LocationInstance[] | null;
  locationCity?: string | null;
  locationRegion?: string | null;
  locationCountry?: string | null;
}): string | null {
  const canonical = joinLocationLabels((job.locations ?? []).map(instanceLabel));
  if (canonical) return canonical;
  const raw = job.location?.trim();
  if (raw && /[|;]/.test(raw)) return compositeLocationLabel(raw);
  const structured = [job.locationCity, job.locationRegion, job.locationCountry]
    .filter(Boolean)
    .map((part) => formatLocationSegment(part!))
    .join(", ");
  if (structured) return structured;
  return formatLocationText(job.location);
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
