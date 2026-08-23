import { toast } from "sonner";

import type { RunRecord } from "./store";

/**
 * Completions arrive one at a time on the live path and in batches when a
 * client reconnects after a disconnect. Past this many in one batch, individual
 * toasts stop being information and start being a wall — so the batch collapses
 * into a single summary. The cap limits noise only; every run is still acked.
 */
export const ANNOUNCE_TOAST_CAP = 3;

function announceOne(run: RunRecord): void {
  if (run.status === "failed") {
    toast.error(`${run.kind} failed: ${run.error ?? "unknown error"}`);
    return;
  }
  if (run.status === "cancelled") {
    toast.info(`${run.kind} cancelled`);
    return;
  }
  if (run.kind === "tailor") {
    const rawJobs = (run.result as { jobs?: unknown } | null)?.jobs;
    const jobs: unknown[] = Array.isArray(rawJobs) ? rawJobs : [];
    const versions = jobs.reduce<number>((total, job) => {
      const count = (job as { versionCount?: unknown } | null)?.versionCount;
      return total + (typeof count === "number" ? count : 0);
    }, 0);
    toast.success(
      `Tailoring complete: ${versions} resume versions created. Open a job's Versions tab to render PDF.`,
    );
    return;
  }
  if (run.kind === "refreshClusters") {
    const result = (run.result as Record<string, unknown> | null) ?? {};
    const count = (key: string) =>
      typeof result[key] === "number" ? result[key] : 0;
    toast.success(
      `Regroup complete: ${count("assignedSkills")} assigned · ${count("aliasesMerged")} aliases merged · ${count("domainsCreated")} domains created · ${count("uncertainSkills")} uncertain · ${count("failedSkills")} failed · ${count("skippedStaleSkills")} skipped.`,
    );
    return;
  }
  if (run.kind === "maintainTaxonomy") {
    const result = (run.result as Record<string, unknown> | null) ?? {};
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
  toast.success(`${run.kind} completed`);
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
    toast.success(`${runs.length} runs finished while you were away${detail}.`);
    return;
  }
  for (const run of runs) announceOne(run);
}
