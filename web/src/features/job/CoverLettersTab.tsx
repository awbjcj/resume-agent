import { CoverLetterRow, type CoverLetterItem } from "./CoverLetterRow";

export function CoverLettersTab({
  jobId,
  coverLetters,
  appliedId,
}: {
  jobId: number;
  coverLetters: CoverLetterItem[];
  appliedId: number | null;
}) {
  if (coverLetters.length === 0) {
    return (
      <p className="mt-2 rounded-xl border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
        No cover letter yet.
      </p>
    );
  }

  return (
    <ul className="mt-2 space-y-2">
      {coverLetters.map((coverLetter) => (
        <CoverLetterRow
          key={coverLetter.id}
          jobId={jobId}
          coverLetter={coverLetter}
          appliedId={appliedId}
        />
      ))}
    </ul>
  );
}
