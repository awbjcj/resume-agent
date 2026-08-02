import type { ScoutProposal } from "./use-scout";

/** Whether the API would accept this proposal right now.
 *
 * Declared once because it used to be declared twice and the copies drifted:
 * the row blocked only `avoid`/`failed`/`duplicate` (plus an unprobed source),
 * while the batch button required `check === "validated"`. Only *source*
 * proposals are ever probed into `validated` — `services/scout.py` stamps every
 * fresh proposal `new` and upgrades sources alone — so a turn that proposed
 * search terms left the batch button permanently disabled. It also excluded
 * `unverified` scrape targets, which `approve_proposal` explicitly accepts.
 *
 * Mirrors `services/scout.py::approve_proposal`: a source must be `validated`,
 * or `unverified` with a local browser; a term needs only to not be a duplicate.
 */
export function canAddProposal(row: ScoutProposal, scrapeAvailable: boolean): boolean {
  if (row.status !== "pending") return false;
  if (row.check === "duplicate" || row.check === "avoid") return false;
  if (row.kind !== "source") return row.check !== "failed";
  if (row.check === "validated") return true;
  if (row.check === "unverified") return scrapeAvailable;
  return false;
}

/** Why an otherwise-pending proposal cannot be added, for the row to explain. */
export function blockedReason(row: ScoutProposal, scrapeAvailable: boolean): string {
  if (row.status !== "pending" || canAddProposal(row, scrapeAvailable)) return "";
  if (row.check === "duplicate") return "Already in your workspace.";
  if (row.check === "avoid") return "Flagged to avoid, so it cannot be added.";
  if (row.check === "failed") return "This source could not be verified.";
  if (row.check === "unverified" && !scrapeAvailable)
    return "Browser scraping is unavailable, so this source cannot be verified and added yet.";
  return "Still being checked.";
}

export function proposalBadge(row: ScoutProposal): string {
  if (row.status === "added") return "Added";
  if (row.status === "dismissed") return "Dismissed";
  if (row.check === "validated") return row.source?.roleCount == null ? "Validated" : `${row.source.roleCount} roles`;
  if (row.check === "unverified") return "Scrape target";
  if (row.check === "duplicate") return "Already in sources";
  if (row.check === "avoid") return "Avoid";
  if (row.check === "failed") return "Failed";
  return "New";
}

export function proposalLabel(row: ScoutProposal): string {
  return row.source?.company ?? row.term?.value ?? "Proposal";
}

/** Secondary line: the ATS for a company, the term kind for a search condition. */
export function proposalDetail(row: ScoutProposal): string {
  return row.source?.ats ?? row.term?.termKind.replaceAll("_", " ") ?? "";
}

export type ProposalGroups = {
  companies: ScoutProposal[];
  terms: ScoutProposal[];
  resolved: ScoutProposal[];
};

/** Split the ledger into the sections the rail renders.
 *
 * `locallyAdded` carries rows a batch run has already approved but whose
 * refetch has not landed yet, so they move to Resolved immediately instead of
 * sitting in the pending list offering an Add button that would now 409.
 */
export function groupProposals(
  rows: readonly ScoutProposal[],
  locallyAdded: readonly string[] = [],
): ProposalGroups {
  const groups: ProposalGroups = { companies: [], terms: [], resolved: [] };
  for (const row of rows) {
    if (row.status !== "pending" || locallyAdded.includes(row.id)) groups.resolved.push(row);
    else if (row.kind === "source") groups.companies.push(row);
    else groups.terms.push(row);
  }
  return groups;
}
