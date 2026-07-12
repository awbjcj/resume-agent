import { useId, useState } from "react";
import { CheckCircle2, Download, FileText, Loader2, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { openDownload } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import {
  useRenderVersion,
  useReviseVersion,
  useSelectResume,
} from "./use-job-mutations";

type ResumeVersion = components["schemas"]["ResumeVersionOut"] & {
  origin?: string;
  instruction?: string | null;
  parentVersionId?: number | null;
};

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
  const select = useSelectResume(jobId);
  const applied = appliedVersionId === version.id;
  const origin = version.origin ?? "tailor";
  const isRevision = origin === "revision";

  return (
    <li className="rounded-xl border bg-background/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={isRevision ? "secondary" : "outline"}>
              {isRevision ? "Revision" : `Round ${version.round}`}
            </Badge>
            <span className="text-muted-foreground">Score {version.reviewScore ?? "not scored"}</span>
            <Badge variant={version.factCheckPassed ? "outline" : "destructive"}>
              {version.factCheckPassed ? "Fact-check passed" : "Fact-check failed"}
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
          disabled={!instruction.trim() || revise.isPending}
          onClick={() =>
            revise.mutate(
              { versionId: version.id, instruction, reReview },
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
