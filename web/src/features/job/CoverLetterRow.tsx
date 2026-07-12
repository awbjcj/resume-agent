import { useState } from "react";
import { CheckCircle2, Download, FileText, Loader2, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { openDownload } from "@/lib/api/client";
import {
  useReviseCoverLetter,
  useSelectCoverLetter,
} from "./use-job-mutations";

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
  const select = useSelectCoverLetter(jobId);
  const applied = appliedId === coverLetter.id;
  const origin = coverLetter.origin ?? "draft";
  const isRevision = origin === "revision";

  return (
    <li className="rounded-xl border bg-background/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={isRevision ? "secondary" : "outline"}>
              {isRevision ? "Revision" : "Draft"}
            </Badge>
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
        />
        <Button
          size="sm"
          disabled={!instruction.trim() || revise.isPending}
          onClick={() =>
            revise.mutate(
              { coverLetterId: coverLetter.id, instruction },
              { onSuccess: () => setInstruction("") },
            )
          }
        >
          {revise.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="size-4" aria-hidden="true" />
          )}
          Revise
        </Button>
      </div>
    </li>
  );
}
