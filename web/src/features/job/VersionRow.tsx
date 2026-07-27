import { useId, useState } from "react";
import { CheckCircle2, Download, FileText, Loader2, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { openDownload } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useRunStore } from "@/lib/runs/store";
import {
  useRenderVersion,
  useReviseVersion,
  useSelectResume,
} from "./use-job-mutations";
import {
  ACTIVE_RUN_STATUSES,
  latestArtifactRun,
  runCreatedArtifact,
} from "./artifact-runs";

type ResumeVersion = components["schemas"]["ResumeVersionOut"] & {
  origin?: string;
  instruction?: string | null;
  parentVersionId?: number | null;
};

/**
 * `factCheckPassed` is the AND of every gate, so on its own it labelled a
 * provenance-only failure as a fact-check failure on rounds where the
 * fact-check reviewer never ran. `failedGates` says which one actually blocked.
 */
export function failedGateLabel(failedGates: readonly string[] | undefined) {
  if (!failedGates?.length) return "Fact-lock failed";
  return `Fact-lock failed — ${failedGates.join(", ")}`;
}

export function VersionRow({
  jobId,
  version,
  appliedVersionId,
}: {
  jobId: number;
  version: ResumeVersion;
  appliedVersionId: number | null;
}) {
  const [instruction, setInstruction] = useState("");
  const [reReview, setReReview] = useState(false);
  const checkboxId = useId();
  const render = useRenderVersion(jobId);
  const revise = useReviseVersion(jobId);
  const runs = useRunStore((state) => state.runs);
  const reviseRun = latestArtifactRun(runs, "revise", "versionId", version.id);
  const reviseActive =
    reviseRun !== undefined && ACTIVE_RUN_STATUSES.includes(reviseRun.status);
  const justCreated = runCreatedArtifact(runs, "revise", "versionId", version.id);
  const select = useSelectResume(jobId);
  const applied = appliedVersionId === version.id;
  const origin = version.origin ?? "tailor";
  const isRevision = origin === "revision";

  return (
    <li
      className={`rounded-xl border bg-background/70 p-3 ${
        justCreated ? "ring-2 ring-primary/40" : ""
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={isRevision ? "secondary" : "outline"}>
              {isRevision ? "Revision" : `Round ${version.round}`}
            </Badge>
            {justCreated ? <Badge>Just created</Badge> : null}
            <span className="text-muted-foreground">Score {version.reviewScore ?? "not scored"}</span>
            <Badge variant={version.factCheckPassed ? "outline" : "destructive"}>
              {version.factCheckPassed
                ? "Fact-lock passed"
                : failedGateLabel(version.failedGates)}
            </Badge>
            {version.parentVersionId && (
              <span className="text-xs text-muted-foreground">
                from version #{version.parentVersionId}
              </span>
            )}
          </div>
          {version.instruction && (
            <p className="max-w-[56rem] text-sm leading-6 text-muted-foreground">
              {version.instruction}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={applied ? "default" : "outline"}
            disabled={select.isPending}
            onClick={() => select.mutate(version.id)}
          >
            <CheckCircle2 className="size-4" aria-hidden="true" />
            {applied ? "Applied" : "Use for application"}
          </Button>
          {version.pdfPath ? (
            <Button size="sm" variant="outline" render={
              <a
                href={`/api/resume-versions/${version.id}/pdf`}
                onClick={(event) => {
                  event.preventDefault();
                  void openDownload(event.currentTarget.href);
                }}
              >
                <Download className="size-4" aria-hidden="true" />
                Download
              </a>
            } />
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={render.isPending}
              onClick={() => render.mutate(version.id)}
            >
              {render.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <FileText className="size-4" aria-hidden="true" />
              )}
              Render
            </Button>
          )}
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
        <Input
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Revise this version"
          aria-label="Resume revision instruction"
          disabled={reviseActive}
        />
        <label
          htmlFor={checkboxId}
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Checkbox
            id={checkboxId}
            checked={reReview}
            onCheckedChange={(value) => setReReview(Boolean(value))}
          />
          Re-review
        </label>
        <Button
          size="sm"
          disabled={!instruction.trim() || revise.isPending || reviseActive}
          onClick={() => {
            const nextInstruction = instruction.trim();
            setInstruction("");
            revise.mutate({
              versionId: version.id,
              instruction: nextInstruction,
              reReview,
            });
          }}
        >
          {revise.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="size-4" aria-hidden="true" />
          )}
          Revise
        </Button>
      </div>
      {reviseRun && reviseActive ? (
        <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          <Spinner data-icon="inline-start" />
          Revision in progress
        </p>
      ) : null}
      {reviseRun?.status === "failed" ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert">
          <span>Revision failed: {reviseRun.error ?? "unknown error"}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              revise.mutate({
                versionId: version.id,
                instruction: reviseRun.meta?.instruction ?? "",
                reReview: Boolean(reviseRun.meta?.reReview),
              })
            }
          >
            <RotateCcw data-icon="inline-start" />
            Retry
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Dismiss revision error"
            onClick={() => useRunStore.getState().remove(reviseRun.runId)}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </li>
  );
}
