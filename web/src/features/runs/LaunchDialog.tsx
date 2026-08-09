import { useState } from "react";

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

export function LaunchDialog(props: LaunchDialogProps) {
  // Bump `openSeq` only on the closed->open transition. Base UI's Dialog
  // popup stays mounted through its exit animation to play the close
  // transition; remounting LaunchDialogBody (and the popup inside it) via a
  // key change at that exact moment strands a freshly-mounted, already-open
  // popup that never receives the animation-end signal that would hide it,
  // so it never closes. Reacting only to opening keeps the still-closing
  // instance untouched while still resetting `selected` on every fresh open.
  const [openState, setOpenState] = useState(() => ({
    isOpen: props.open,
    sequence: 0,
  }));
  if (props.open !== openState.isOpen) {
    setOpenState({
      isOpen: props.open,
      sequence: props.open ? openState.sequence + 1 : openState.sequence,
    });
  }

  const resetKey = [
    openState.sequence,
    props.mode,
    props.isLoading,
    props.error,
    ...props.jobs.map((job) => job.jobId),
  ].join(":");
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <LaunchDialogBody key={resetKey} {...props} />
    </Dialog>
  );
}

function LaunchDialogBody({
  mode,
  jobs,
  isLoading = false,
  error = null,
  onRetry,
  onOpenChange,
  onLaunch,
}: LaunchDialogProps) {
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(jobs.map((job) => job.jobId)),
  );
  const [deep, setDeep] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);

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
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>
          {mode === "tailor" ? "Tailor resumes" : "Write cover letters"}
        </DialogTitle>
        <DialogDescription>
          {mode === "tailor"
            ? "Choose which approved jobs to process. All jobs start selected."
            : "Choose jobs that have passed approval, including tailored or rendered jobs. All jobs start selected."}
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
            <EmptyTitle>
              {mode === "tailor" ? "No approved jobs" : "No eligible jobs"}
            </EmptyTitle>
            <EmptyDescription>
              {mode === "tailor"
                ? "Approve a job before launching this workflow."
                : "Approve a job before writing its cover letter."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <FieldSet>
          <FieldLegend variant="label">
            {mode === "tailor" ? "Approved jobs" : "Eligible jobs"}
          </FieldLegend>
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
  );
}
