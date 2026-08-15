import { useMemo } from "react";

import type { components } from "@/lib/api/schema";
import { ArtifactSelectionBar } from "./ArtifactSelectionBar";
import { RevisionRunPlaceholders } from "./RevisionRunPlaceholders";
import { useArtifactSelection } from "./use-artifact-selection";
import { useDeleteVersions } from "./use-job-mutations";
import { VersionRow } from "./VersionRow";

type ResumeVersion = components["schemas"]["ResumeVersionOut"];

/**
 * The resume-version list, extracted from JobModal so checkbox selection has
 * somewhere to live: the bulk-delete bar and the per-row checkboxes have to
 * share one selection, and the rows themselves are siblings.
 */
export function ResumeVersionsTab({
  jobId,
  versions,
  appliedVersionId,
}: {
  jobId: number;
  versions: ResumeVersion[];
  appliedVersionId: number | null;
}) {
  // The applied version is not deletable, so it is not selectable either.
  const deletableIds = useMemo(
    () => versions.map((v) => v.id).filter((id) => id !== appliedVersionId),
    [versions, appliedVersionId],
  );
  const selection = useArtifactSelection(deletableIds);
  const remove = useDeleteVersions(jobId);

  return (
    <>
      {deletableIds.length > 0 && (
        <ArtifactSelectionBar
          noun="version"
          selectedCount={selection.selectedIds.length}
          allSelected={selection.allSelected}
          onToggleAll={selection.toggleAll}
          disabled={remove.isPending}
          onDelete={() =>
            remove.mutate(selection.selectedIds, { onSuccess: selection.clear })
          }
        />
      )}
      <ul className="mt-4 space-y-3">
        {versions.map((version) => (
          <VersionRow
            key={version.id}
            jobId={jobId}
            version={version}
            appliedVersionId={appliedVersionId}
            selected={selection.isSelected(version.id)}
            onToggleSelected={selection.toggle}
          />
        ))}
        <RevisionRunPlaceholders jobId={jobId} kind="revise" label="Resume revision" />
      </ul>
    </>
  );
}
