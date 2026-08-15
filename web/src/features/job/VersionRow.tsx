import { useId, useState } from "react";
import { CheckCircle2, Download, Eye, FileText, Loader2, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { openDownload } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { ArtifactDeleteButton } from "./ArtifactDeleteButton";
import { PdfPreviewDialog } from "./PdfPreviewDialog";
import {
  useDeleteVersions,
  useDeselectResume,
  useRenderVersion,
  useReviseVersion,
  useSelectResume,
} from "./use-job-mutations";
import {
  dismissArtifactRun,
  resumeRevisionLifecycle,
  useArtifactRunIndex,
} from "./artifact-runs";
import { EvidencePortfolioDisclosure } from "./EvidencePortfolioDisclosure";

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
  selected = false,
  onToggleSelected,
}: {
  jobId: number;
  version: ResumeVersion;
  appliedVersionId: number | null;
  selected?: boolean;
  onToggleSelected?: (id: number) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [reReview, setReReview] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const checkboxId = useId();
  const render = useRenderVersion(jobId);
  const revise = useReviseVersion(jobId);
  const runIndex = useArtifactRunIndex();
  const revision = resumeRevisionLifecycle(runIndex, version.id);
  const reviseRun = revision.run;
  const reviseActive = revision.active;
  const justCreated = revision.justCreated;
  const select = useSelectResume(jobId);
  const deselect = useDeselectResume(jobId);
  const remove = useDeleteVersions(jobId);
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
        <div className="flex min-w-0 items-start gap-3">
          {onToggleSelected && (
            <Checkbox
              className="mt-1"
              checked={selected}
              disabled={applied}
              onCheckedChange={() => onToggleSelected(version.id)}
              aria-label={`Select round ${version.round} for deletion`}
            />
          )}
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
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {/* A toggle: clicking an applied version unselects it, which is also
              how the user gets past the delete gate below. */}
          <Button
            size="sm"
            variant={applied ? "default" : "outline"}
            disabled={select.isPending || deselect.isPending}
            title={applied ? "Click to unselect" : undefined}
            onClick={() =>
              applied ? deselect.mutate() : select.mutate(version.id)
            }
          >
            <CheckCircle2 className="size-4" aria-hidden="true" />
            {applied ? "Applied" : "Use for application"}
          </Button>
          {version.pdfPath ? (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPreviewOpen(true)}
              >
                <Eye className="size-4" aria-hidden="true" />
                Preview
              </Button>
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
            </>
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
          <ArtifactDeleteButton
            noun="version"
            label={isRevision ? "this revision" : `round ${version.round}`}
            applied={applied}
            disabled={remove.isPending || reviseActive}
            onConfirm={() => remove.mutate([version.id])}
          />
          {/* Portalled, so it costs nothing here and cannot be unmounted
              mid-view by `pdfPath` going falsy while the preview is open. */}
          <PdfPreviewDialog
            open={previewOpen}
            onOpenChange={setPreviewOpen}
            title={
              isRevision
                ? "Resume revision preview"
                : `Round ${version.round} preview`
            }
            previewPath={`/api/resume-versions/${version.id}/preview`}
            downloadPath={`/api/resume-versions/${version.id}/pdf`}
          />
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
            onClick={() => revision.retryInput && revise.mutate(revision.retryInput)}
          >
            <RotateCcw data-icon="inline-start" />
            Retry
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Dismiss revision error"
            onClick={() => dismissArtifactRun(reviseRun.runId)}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ) : null}
      <EvidencePortfolioDisclosure
        versionId={version.id}
        available={version.hasEvidencePortfolio}
      />
    </li>
  );
}
