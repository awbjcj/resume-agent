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

// A dotted abbreviation ("U.S", "U.S.", "N.Y.") is single letters joined by
// periods -- the generic per-word capitalize-first-lowercase-rest pass below
// would otherwise turn it into "U.s", since "." isn't a recognized separator.
const DOTTED_ABBREVIATION_RE = /^[A-Za-z](\.[A-Za-z])*\.?$/;

function titleCaseWord(word: string): string {
  if (DOTTED_ABBREVIATION_RE.test(word)) return word.toUpperCase();
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

// Connector words that stay lowercase mid-phrase in a job-brief label ("Media
// and Entertainment", not "Media And Entertainment"); still capitalized when
// they're the label's first word. "and/or" is never capitalized -- it never
// reads as a title, first word or not.
const LOWERCASE_FIELD_CONNECTORS = new Set([
  "and", "or", "of", "the", "in", "for", "&", "nor", "a", "an", "to", "with", "vs",
]);
const ALWAYS_LOWERCASE_FIELD_WORDS = new Set(["and/or"]);

// Abbreviations that must render fully upper-case rather than title-cased
// ("ai" -> "AI", not "Ai"; "h1b" -> "H1B", not "H1b") wherever a job-brief
// field (remote policy, sponsorship, seniority, industry, source, ...) is
// displayed.
const UPPERCASE_FIELD_ACRONYMS = new Set([
  "ai", "ml", "nlp", "llm", "llms", "api", "apis", "sql", "aws", "gcp", "iot",
  "ui", "ux", "seo", "sem", "hr", "it", "qa", "pr",
  "b2b", "b2c", "r&d", "hipaa", "sox", "gdpr", "kyc", "aml", "cpa", "mba",
  "phd", "h1b", "us", "uk", "eu", "usa", "vp", "svp", "ceo", "cto", "cfo", "coo",
]);
const MIXED_CASE_FIELD_ACRONYMS = new Map([
  ["saas", "SaaS"],
  ["paas", "PaaS"],
  ["iaas", "IaaS"],
]);

function fieldLabelWord(word: string, isFirst: boolean): string {
  const lower = word.toLowerCase();
  if (ALWAYS_LOWERCASE_FIELD_WORDS.has(lower)) return lower;
  const mixedCase = MIXED_CASE_FIELD_ACRONYMS.get(lower);
  if (mixedCase) return mixedCase;
  if (UPPERCASE_FIELD_ACRONYMS.has(lower)) return lower.toUpperCase();
  if (!isFirst && LOWERCASE_FIELD_CONNECTORS.has(lower)) return lower;
  return titleCaseWord(word);
}

/** The single source of truth for rendering a raw job-brief enum/free-text
 * value (seniority, remote policy, sponsorship, employment type, industry,
 * source, ...) as a readable label anywhere in the UI: underscores become
 * spaces, connectors stay lowercase, known acronyms render upper-case, and
 * everything else is title-cased. */
export function fieldLabel(value: string | null | undefined): string {
  if (!value) return "";
  const words = value.replaceAll("_", " ").trim().split(/\s+/).filter(Boolean);
  return words.map((word, i) => fieldLabelWord(word, i === 0)).join(" ");
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
    fieldLabel(row.seniority),
    fieldLabel(row.employmentType),
    fieldLabel(row.industry),
    recency(row.postedAt),
  ].filter((p): p is string => Boolean(p));
}
