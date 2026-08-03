import { Archive, ArchiveRestore, ExternalLink, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button, buttonVariants } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";
import { H1BCheckButton } from "./H1BCheckButton";
import { useArchiveJob } from "./use-archive-job";
import { useDeleteJob } from "./use-delete-job";

type H1BStatus = components["schemas"]["H1BSponsorshipEvidenceOut"]["status"];

export function JobQuickActions({
  jobId,
  company,
  url,
  h1bStatus,
  archived = false,
  allowDelete = false,
}: {
  jobId: number;
  company?: string | null;
  url?: string | null;
  h1bStatus?: H1BStatus | null;
  archived?: boolean;
  allowDelete?: boolean;
}) {
  const archiveJob = useArchiveJob();
  const deleteJob = useDeleteJob();
  return (
    <>
      <H1BCheckButton
        jobId={jobId}
        company={company}
        initialStatus={h1bStatus}
      />
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          aria-label="Open posting"
          className={cn(buttonVariants({ size: "icon-sm", variant: "ghost" }))}
        >
          <ExternalLink aria-hidden="true" />
        </a>
      )}
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={archived ? "Restore job" : "Archive job"}
        disabled={archiveJob.isPending}
        onClick={() => archiveJob.mutate({ jobId, archived: !archived })}
      >
        {archived ? <ArchiveRestore aria-hidden="true" /> : <Archive aria-hidden="true" />}
      </Button>
      {allowDelete && (
        <ConfirmDialog
          trigger={<Button size="icon-sm" variant="ghost" aria-label="Delete job"><Trash2 aria-hidden="true" /></Button>}
          title="Delete this job?"
          description="Deletion is permanent. Jobs with progress are refused."
          confirmLabel="Delete"
          confirmDisabled={deleteJob.isPending}
          onConfirm={() => deleteJob.mutateAsync(jobId)}
        />
      )}
    </>
  );
}
