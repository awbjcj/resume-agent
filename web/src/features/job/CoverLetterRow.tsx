import { useState } from "react";
import { CheckCircle2, Download, Eye, FileText, Loader2, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { openDownload } from "@/lib/api/client";
import { ArtifactDeleteButton } from "./ArtifactDeleteButton";
import { PdfPreviewDialog } from "./PdfPreviewDialog";
import {
  useDeleteCoverLetters,
  useDeselectCoverLetter,
  useReviseCoverLetter,
  useSelectCoverLetter,
} from "./use-job-mutations";
import {
  coverLetterRevisionLifecycle,
  dismissArtifactRun,
  useArtifactRunIndex,
} from "./artifact-runs";

export type CoverLetterItem = {
  id: number;
  jobId: number;
  resumeVersionId?: number | null;
  origin?: string;
  instruction?: string | null;
  parentId?: number | null;
  factCheckPassed: boolean;
  pdfPath?: string | null;
  createdAt?: string;
};

export function CoverLetterRow({
  jobId,
  coverLetter,
  appliedId,
  selected = false,
  onToggleSelected,
}: {
  jobId: number;
  coverLetter: CoverLetterItem;
  appliedId: number | null;
  selected?: boolean;
  onToggleSelected?: (id: number) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const revise = useReviseCoverLetter(jobId);
  const runIndex = useArtifactRunIndex();
  const revision = coverLetterRevisionLifecycle(runIndex, coverLetter.id);
  const reviseRun = revision.run;
  const reviseActive = revision.active;
  const justCreated = revision.justCreated;
  const select = useSelectCoverLetter(jobId);
  const deselect = useDeselectCoverLetter(jobId);
  const remove = useDeleteCoverLetters(jobId);
  const applied = appliedId === coverLetter.id;
  const origin = coverLetter.origin ?? "draft";
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
              onCheckedChange={() => onToggleSelected(coverLetter.id)}
              aria-label={`Select cover letter #${coverLetter.id} for deletion`}
            />
          )}
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant={isRevision ? "secondary" : "outline"}>
                {isRevision ? "Revision" : "Draft"}
              </Badge>
              {justCreated ? <Badge>Just created</Badge> : null}
              <Badge variant={coverLetter.factCheckPassed ? "outline" : "destructive"}>
                {coverLetter.factCheckPassed ? "Fact-check passed" : "Fact-check failed"}
              </Badge>
              {coverLetter.parentId && (
                <span className="text-xs text-muted-foreground">
                  from cover letter #{coverLetter.parentId}
                </span>
              )}
            </div>
            {coverLetter.instruction && (
              <p className="max-w-[56rem] text-sm leading-6 text-muted-foreground">
                {coverLetter.instruction}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {/* A toggle: clicking an applied letter unselects it, which is also
              how the user gets past the delete gate below. */}
          <Button
            size="sm"
            variant={applied ? "default" : "outline"}
            disabled={select.isPending || deselect.isPending}
            title={applied ? "Click to unselect" : undefined}
            onClick={() =>
              applied ? deselect.mutate() : select.mutate(coverLetter.id)
            }
          >
            <CheckCircle2 className="size-4" aria-hidden="true" />
            {applied ? "Applied" : "Use for application"}
          </Button>
          {coverLetter.pdfPath ? (
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
                  href={`/api/cover-letters/${coverLetter.id}/pdf`}
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
            <span className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm text-muted-foreground">
              <FileText className="size-4" aria-hidden="true" />
              No PDF
            </span>
          )}
          <ArtifactDeleteButton
            noun="cover letter"
            label={isRevision ? "this revision" : "this cover letter"}
            applied={applied}
            disabled={remove.isPending || reviseActive}
            onConfirm={() => remove.mutate([coverLetter.id])}
          />
          {/* Portalled, so it costs nothing here and cannot be unmounted
              mid-view by `pdfPath` going falsy while the preview is open. */}
          <PdfPreviewDialog
            open={previewOpen}
            onOpenChange={setPreviewOpen}
            title={
              isRevision ? "Cover letter revision preview" : "Cover letter preview"
            }
            previewPath={`/api/cover-letters/${coverLetter.id}/preview`}
            downloadPath={`/api/cover-letters/${coverLetter.id}/pdf`}
          />
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <Input
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Revise this cover letter"
          aria-label="Cover letter revision instruction"
          disabled={reviseActive}
        />
        <Button
          size="sm"
          disabled={!instruction.trim() || revise.isPending || reviseActive}
          onClick={() => {
            const nextInstruction = instruction.trim();
            setInstruction("");
            revise.mutate({ coverLetterId: coverLetter.id, instruction: nextInstruction });
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
          Cover-letter revision in progress
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
    </li>
  );
}
