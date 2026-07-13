import { useState } from "react";
import { CheckCircle2, Download, FileText, Loader2, RotateCcw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { openDownload } from "@/lib/api/client";
import { useRunStore } from "@/lib/runs/store";
import {
  useReviseCoverLetter,
  useSelectCoverLetter,
} from "./use-job-mutations";
import {
  ACTIVE_RUN_STATUSES,
  latestArtifactRun,
  runCreatedArtifact,
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
}: {
  jobId: number;
  coverLetter: CoverLetterItem;
  appliedId: number | null;
}) {
  const [instruction, setInstruction] = useState("");
  const revise = useReviseCoverLetter(jobId);
  const runs = useRunStore((state) => state.runs);
  const reviseRun = latestArtifactRun(
    runs,
    "coverLetterRevise",
    "coverLetterId",
    coverLetter.id,
  );
  const reviseActive =
    reviseRun !== undefined && ACTIVE_RUN_STATUSES.includes(reviseRun.status);
  const justCreated = runCreatedArtifact(
    runs,
    "coverLetterRevise",
    "coverLetterId",
    coverLetter.id,
  );
  const select = useSelectCoverLetter(jobId);
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
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={applied ? "default" : "outline"}
            disabled={select.isPending}
            onClick={() => select.mutate(coverLetter.id)}
          >
            <CheckCircle2 className="size-4" aria-hidden="true" />
            {applied ? "Applied" : "Use for application"}
          </Button>
          {coverLetter.pdfPath ? (
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
          ) : (
            <span className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm text-muted-foreground">
              <FileText className="size-4" aria-hidden="true" />
              No PDF
            </span>
          )}
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
            onClick={() =>
              revise.mutate({
                coverLetterId: coverLetter.id,
                instruction: reviseRun.meta?.instruction ?? "",
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
