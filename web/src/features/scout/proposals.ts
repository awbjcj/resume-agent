import type { ScoutProposal } from "./use-scout";

/** Whether normal approval can reach the server for this proposal. */
export function canAddProposal(row: ScoutProposal): boolean {
  if (row.status !== "pending") return false;
  if (row.kind === "source") return row.check === "validated";
  return row.check === "new";
}

/** Whether the warned, audited override path is available for this source. */
export function canManuallyConfirm(
  row: ScoutProposal,
  scrapeAvailable: boolean,
): boolean {
  if (row.status !== "pending" || row.kind !== "source" || row.check !== "unverified") return false;
  return row.source?.ats != null || scrapeAvailable;
}

export function verificationLabel(
  row: ScoutProposal,
): "Verified" | "Unverified" | "Ownership conflict" | null {
  if (row.kind !== "source") return null;
  if (row.check === "validated") return "Verified";
  if (row.check === "unverified") return "Unverified";
  if (row.check === "conflict") return "Ownership conflict";
  return null;
}

/** Why an otherwise-pending proposal cannot be added, for the row to explain. */
export function blockedReason(row: ScoutProposal, scrapeAvailable: boolean): string {
  if (row.status !== "pending" || canAddProposal(row)) return "";
  if (row.check === "duplicate") return "Already in your workspace.";
  if (row.check === "avoid") return "Flagged to avoid, so it cannot be added.";
  if (row.check === "conflict") return "Provider metadata identifies this board as a different company.";
  if (row.check === "failed") return "This source could not be verified.";
  if (row.check === "unverified" && canManuallyConfirm(row, scrapeAvailable))
    return "This board is unverified. You can review it and explicitly confirm it if it is correct.";
  if (row.check === "unverified" && !scrapeAvailable)
    return "Browser scraping is unavailable, so an unsupported board cannot be manually added.";
  return "Still being checked.";
}

export function proposalBadge(row: ScoutProposal): string {
  if (row.status === "added") return "Added";
  if (row.status === "dismissed") return "Dismissed";
  if (row.check === "validated") return "Verified";
  if (row.check === "unverified") return "Unverified";
  if (row.check === "conflict") return "Ownership conflict";
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
