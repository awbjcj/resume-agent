import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";

export interface LaunchJob {
  jobId: number;
  company: string | null;
  title: string | null;
}

interface LaunchDialogProps {
  mode: "tailor" | "coverLetter";
  jobs: LaunchJob[];
  open: boolean;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onOpenChange: (open: boolean) => void;
  onLaunch: (jobIds: number[], deep: boolean) => Promise<boolean>;
}

export function LaunchDialog({
  mode,
  jobs,
  open,
  isLoading = false,
  error = null,
  onRetry,
  onOpenChange,
  onLaunch,
}: LaunchDialogProps) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deep, setDeep] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);

  useEffect(() => {
    if (open && !isLoading && !error) {
      setSelected(new Set(jobs.map((job) => job.jobId)));
      setDeep(false);
    }
  }, [error, isLoading, jobs, open]);

  const count = selected.size;
  const submitLabel =
    mode === "tailor"
      ? `Tailor ${count} job${count === 1 ? "" : "s"}`
      : `Write ${count} cover letter${count === 1 ? "" : "s"}`;
  const unavailable = isLoading || Boolean(error) || jobs.length === 0;

  const submit = async () => {
    setIsLaunching(true);
    try {
      const launched = await onLaunch([...selected], deep);
      if (launched) onOpenChange(false);
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === "tailor" ? "Tailor resumes" : "Write cover letters"}
          </DialogTitle>
          <DialogDescription>
            Choose which approved jobs to process. All jobs start selected.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>Loading approved jobs</EmptyTitle>
              <EmptyDescription>Collecting every pipeline page…</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : error ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>Approved jobs unavailable</EmptyTitle>
              <EmptyDescription>{error}</EmptyDescription>
            </EmptyHeader>
            {onRetry && (
              <EmptyContent>
                <Button variant="outline" onClick={onRetry}>Retry</Button>
              </EmptyContent>
            )}
          </Empty>
        ) : jobs.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No approved jobs</EmptyTitle>
              <EmptyDescription>Approve a job before launching this workflow.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <FieldSet>
            <FieldLegend variant="label">Approved jobs</FieldLegend>
            <FieldGroup className="max-h-72 overflow-y-auto pr-1">
              {jobs.map((job) => {
                const inputId = `launch-job-${job.jobId}`;
                return (
                  <Field key={job.jobId} orientation="horizontal">
                    <Checkbox
                      id={inputId}
                      checked={selected.has(job.jobId)}
                      disabled={isLaunching}
                      onCheckedChange={(checked) =>
                        setSelected((current) => {
                          const next = new Set(current);
                          if (checked) next.add(job.jobId);
                          else next.delete(job.jobId);
                          return next;
                        })
                      }
                    />
                    <FieldLabel htmlFor={inputId}>
                      {job.company ?? "Unknown company"} — {job.title ?? "Untitled role"}
                    </FieldLabel>
                  </Field>
                );
              })}
            </FieldGroup>
          </FieldSet>
        )}

        {mode === "tailor" && !unavailable && (
          <Field orientation="horizontal">
            <Switch
              id="deep-review"
              checked={deep}
              disabled={isLaunching}
              onCheckedChange={setDeep}
            />
            <div>
              <FieldLabel htmlFor="deep-review">Deep review</FieldLabel>
              <FieldDescription>Full review panel; roughly 3–6× slower.</FieldDescription>
            </div>
          </Field>
        )}

        <DialogFooter>
          <Button variant="outline" disabled={isLaunching} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={unavailable || count === 0 || isLaunching}
            onClick={submit}
          >
            {isLaunching && <Spinner data-icon="inline-start" />}
            {isLaunching ? "Starting…" : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
