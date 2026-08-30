import { toast } from "sonner";

import type { RunRecord } from "./store";

/**
 * Completions arrive one at a time on the live path and in batches when a
 * client reconnects after a disconnect. Past this many in one batch, individual
 * toasts stop being information and start being a wall — so the batch collapses
 * into a single summary. The cap limits noise only; every run is still acked.
 */
export const ANNOUNCE_TOAST_CAP = 3;

const RUN_LABELS: Record<string, string> = {
  addJobUrl: "Job import",
  coverLetter: "Cover-letter generation",
  coverLetterRevise: "Cover-letter revision",
  companyIntelligence: "Company research",
  discover: "Discovery",
  emailDraft: "Email-draft generation",
  gmailSync: "Gmail sync",
  "github-sync": "GitHub sync",
  h1bSponsorship: "H-1B sponsorship check",
  importUrls: "Job import",
  linkedinScrape: "LinkedIn import",
  maintainTaxonomy: "Taxonomy maintenance",
  "profile-build": "Profile build",
  pull: "Job pull",
  redo: "Pipeline redo",
  refreshClusters: "Skill regrouping",
  refresh: "Job refresh",
  reprocess: "Job reprocessing",
  revise: "Resume revision",
  tailor: "Tailoring",
  undoTaxonomyMaintenance: "Taxonomy maintenance undo",
};

function runLabel(kind: string): string {
  return RUN_LABELS[kind] ?? kind;
}

function resultRecord(run: RunRecord): Record<string, unknown> | null {
  return run.result && typeof run.result === "object" && !Array.isArray(run.result)
    ? run.result as Record<string, unknown>
    : null;
}

function numberField(value: unknown, ...keys: string[]): number | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    if (typeof record[key] === "number") return record[key];
  }
  return null;
}

function pluralLabel(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function announceOne(run: RunRecord): void {
  if (run.status === "failed") {
    toast.error(`${runLabel(run.kind)} failed: ${run.error ?? "unknown error"}`);
    return;
  }
  if (run.status === "cancelled") {
    toast.info(`${runLabel(run.kind)} cancelled`);
    return;
  }
  if (run.kind === "tailor") {
    const rawJobs = resultRecord(run)?.jobs;
    if (!Array.isArray(rawJobs)) {
      toast.success("Tailoring complete. Open a job's Versions tab to render PDF.");
      return;
    }
    const jobs: unknown[] = rawJobs;
    const versionCounts = jobs.map((job) =>
      numberField(job, "versionCount", "version_count"),
    );
    const hasCompleteVersionCounts = versionCounts.every((count) => count !== null);
    const versions = versionCounts.reduce<number>(
      (total, count) => total + (count ?? 0),
      0,
    );
    const jobSummary = pluralLabel(jobs.length, "job");
    toast.success(
      hasCompleteVersionCounts
        ? `Tailoring complete: ${jobSummary} tailored, ${pluralLabel(versions, "resume version")} created. Open a job's Versions tab to render PDF.`
        : `Tailoring complete: ${jobSummary} tailored. Open a job's Versions tab to render PDF.`,
    );
    return;
  }
  if (run.kind === "coverLetter") {
    const coverLetters = resultRecord(run)?.coverLetters;
    toast.success(
      Array.isArray(coverLetters)
        ? `Cover-letter generation complete: ${pluralLabel(coverLetters.length, "cover letter")} created.`
        : "Cover-letter generation complete.",
    );
    return;
  }
  if (run.kind === "redo") {
    const outcomes = resultRecord(run)?.outcomes;
    toast.success(
      Array.isArray(outcomes)
        ? `Pipeline redo complete: ${pluralLabel(outcomes.length, "stage")} processed.`
        : "Pipeline redo complete.",
    );
    return;
  }
  if (run.kind === "refreshClusters") {
    const result = resultRecord(run);
    const fields = result && [
      numberField(result, "assignedSkills", "assigned_skills"),
      numberField(result, "aliasesMerged", "aliases_merged"),
      numberField(result, "domainsCreated", "domains_created"),
      numberField(result, "uncertainSkills", "uncertain_skills"),
      numberField(result, "failedSkills", "failed_skills"),
      numberField(result, "skippedStaleSkills", "skipped_stale_skills"),
    ];
    if (!fields || fields.some((value) => value === null)) {
      toast.success("Skill regrouping complete.");
      return;
    }
    const [assigned, aliases, domains, uncertain, failed, skipped] = fields;
    // Read separately and default to 0: a run recorded before this key existed
    // must still produce the detailed toast rather than falling back to the
    // generic one. "Deferred" is not a verdict -- the escalation cap simply
    // has not reached these yet, and they go first on the next run. Folding
    // them into "uncertain" is what made convergence look like a plateau.
    const deferred = numberField(result, "deferredSkills", "deferred_skills") ?? 0;
    const deferredNote = deferred > 0 ? ` · ${deferred} deferred to next run` : "";
    toast.success(
      `Regroup complete: ${assigned} assigned · ${aliases} aliases merged · ${domains} domains created · ${uncertain} uncertain${deferredNote} · ${failed} failed · ${skipped} skipped.`,
    );
    return;
  }
  if (run.kind === "maintainTaxonomy") {
    const result = resultRecord(run);
    if (!result || typeof result.changed !== "boolean") {
      toast.success("Taxonomy maintenance complete.");
      return;
    }
    const actions = Array.isArray(result.actions) ? result.actions.length : 0;
    toast.success(
      result.changed
        ? `Taxonomy maintenance applied ${actions} change${actions === 1 ? "" : "s"}.`
        : "Taxonomy maintenance found no safe changes.",
    );
    return;
  }
  if (run.kind === "undoTaxonomyMaintenance") {
    toast.success("Restored the previous taxonomy maintenance generation.");
    return;
  }
  toast.success(`${runLabel(run.kind)} completed`);
}

/**
 * Tell the user what finished.
 *
 * Batched rather than per-run because the cap is a property of the batch: a
 * reconnect can surface several completions at once, and deciding "toast or
 * summarise" one run at a time cannot see how many siblings are coming.
 */
export function announceCompletions(runs: readonly RunRecord[]): void {
  if (runs.length === 0) return;
  if (runs.length > ANNOUNCE_TOAST_CAP) {
    const failed = runs.filter((run) => run.status === "failed").length;
    const detail = failed > 0 ? ` (${failed} failed)` : "";
    const summary = `${runs.length} runs finished while you were away${detail}.`;
    // A green toast reporting that everything failed is a lie the user has to
    // read twice. Severity follows the batch.
    if (failed === runs.length) toast.error(summary);
    else toast.success(summary);
    return;
  }
  for (const run of runs) announceOne(run);
}
