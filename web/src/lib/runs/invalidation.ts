/**
 * Which query keys a finished run should refresh.
 *
 * This used to be an argument to `launch()`, which meant a run discovered any
 * other way — by the reconciliation poller, or on page load after the launching
 * tab was gone — refreshed nothing, and the board silently kept stale data.
 * The launch call site is still the most specific source of truth when it
 * exists, so it registers an override; the per-kind map is the fallback for
 * every run this session did not launch.
 */

export const DEFAULT_INVALIDATE = [
  "shortlist",
  "pipeline",
  "triage",
  "job",
] as const;

const BY_KIND: Record<string, readonly string[]> = {
  refreshClusters: ["match-gap"],
  maintainTaxonomy: ["match-gap"],
  undoTaxonomyMaintenance: ["match-gap"],
  "profile-build": ["profile-sources", "match-gap", "setup-status"],
  "github-sync": ["profile-sources"],
  gmailSync: ["notifications"],
};

const overrides = new Map<string, readonly string[]>();

export function rememberInvalidation(
  runId: string,
  keys: readonly string[],
): void {
  overrides.set(runId, [...keys]);
}

export function forgetInvalidation(runId: string): void {
  overrides.delete(runId);
}

export function invalidationKeys(runId: string, kind: string): string[] {
  // Copied, not shared: callers merge these into sets and a leaked reference
  // to BY_KIND would let one completion rewrite the table for every later one.
  return [...(overrides.get(runId) ?? BY_KIND[kind] ?? DEFAULT_INVALIDATE)];
}

export function resetInvalidationForTests(): void {
  overrides.clear();
}
