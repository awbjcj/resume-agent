import { CoverLetterRow, type CoverLetterItem } from "./CoverLetterRow";
import { RevisionRunPlaceholders } from "./RevisionRunPlaceholders";

export function CoverLettersTab({
  jobId,
  coverLetters,
  appliedId,
}: {
  jobId: number;
  coverLetters: CoverLetterItem[];
  appliedId: number | null;
}) {
  return (
    <ul className="mt-2 space-y-2">
      {coverLetters.length === 0 ? (
        <li className="rounded-xl border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
          No cover letter yet.
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
        kind="coverLetterRevise"
        label="Cover-letter revision"
      />
    </ul>
  );
}
