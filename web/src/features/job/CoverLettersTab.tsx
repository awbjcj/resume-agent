import { FilePlus2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useRunStore } from "@/lib/runs/store";

import { ACTIVE_RUN_STATUSES, latestArtifactRun } from "./artifact-runs";
import { CoverLetterRow, type CoverLetterItem } from "./CoverLetterRow";
import { RevisionRunPlaceholders } from "./RevisionRunPlaceholders";
import { useGenerateCoverLetter } from "./use-job-mutations";

export function CoverLettersTab({
  jobId,
  coverLetters,
  appliedId,
}: {
  jobId: number;
  coverLetters: CoverLetterItem[];
  appliedId: number | null;
}) {
  const generate = useGenerateCoverLetter(jobId);
  const runs = useRunStore((state) => state.runs);
  const generateRun = latestArtifactRun(runs, "coverLetter", "jobId", jobId);
  // `generating` is the run-store truth; `isPending` is the brief window before
  // the accepted run reaches the store. Only the former replaces the empty
  // state, so the placeholder below takes over without a gap in between.
  const generating =
    generateRun !== undefined && ACTIVE_RUN_STATUSES.includes(generateRun.status);
  const busy = generate.isPending || generating;
  const empty = coverLetters.length === 0;

  return (
    <>
      <ul className="mt-2 space-y-2">
        {empty && !generating ? (
          <li className="rounded-xl border border-dashed bg-muted/20 p-6 text-center">
            <p className="text-sm font-medium">No cover letter yet</p>
            <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground">
              Draft one from your profile facts and this job description. You can
              revise it afterwards.
            </p>
            <Button
              className="mt-4"
              disabled={busy}
              onClick={() => generate.mutate()}
            >
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <FilePlus2 data-icon="inline-start" />
              )}
              {busy ? "Generating…" : "Generate cover letter"}
            </Button>
          </li>
        ) : null}
        {coverLetters.map((coverLetter) => (
          <CoverLetterRow
            key={coverLetter.id}
            jobId={jobId}
            coverLetter={coverLetter}
            appliedId={appliedId}
          />
        ))}
        <RevisionRunPlaceholders
          jobId={jobId}
          kind="coverLetter"
          label="Cover letter"
        />
        <RevisionRunPlaceholders
          jobId={jobId}
          kind="coverLetterRevise"
          label="Cover-letter revision"
        />
      </ul>
      {empty ? null : (
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => generate.mutate()}
          >
            {busy ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <FilePlus2 data-icon="inline-start" />
            )}
            {busy ? "Generating…" : "Generate another"}
          </Button>
        </div>
      )}
    </>
  );
}
