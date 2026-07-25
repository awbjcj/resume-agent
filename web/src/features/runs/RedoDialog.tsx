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
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";

import type { RedoStage } from "./use-redo-run";

// Pipeline order. The backend re-sorts too, but sending them ordered keeps the
// request readable and the button label honest.
const STAGES: { id: RedoStage; label: string; hint: string }[] = [
  {
    id: "pull",
    label: "Re-pull job description",
    hint: "Re-fetch the posting and replace its text.",
  },
  {
    id: "extract",
    label: "Re-extract criteria & fit score",
    hint: "Rebuild criteria and re-score against your profile.",
  },
  {
    id: "tailor",
    label: "Re-tailor resume",
    hint: "Write a new resume version. Existing versions are kept.",
  },
  { id: "render", label: "Re-render PDF", hint: "Re-render the selected version." },
];

const VERBS: Record<RedoStage, string> = {
  pull: "Re-pull",
  extract: "Re-extract",
  tailor: "Re-tailor",
  render: "Re-render",
};

export interface RedoDialogProps {
  open: boolean;
  jobIds: number[];
  initialStages: RedoStage[];
  onOpenChange: (open: boolean) => void;
  onLaunch: (
    jobIds: number[],
    stages: RedoStage[],
    deep: boolean,
  ) => Promise<boolean>;
}

export function RedoDialog(props: RedoDialogProps) {
  // Same closed->open remount guard as LaunchDialog: Base UI's Dialog stays
  // mounted through its exit animation, so remounting mid-close strands an
  // already-open popup that never hides.
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
  const resetKey = [openState.sequence, props.jobIds.length].join(":");
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <RedoDialogBody key={resetKey} {...props} />
    </Dialog>
  );
}

function RedoDialogBody({
  jobIds,
  initialStages,
  onOpenChange,
  onLaunch,
}: RedoDialogProps) {
  const [selected, setSelected] = useState<Set<RedoStage>>(
    () => new Set(initialStages),
  );
  const [deep, setDeep] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);

  const ordered = STAGES.filter((stage) => selected.has(stage.id)).map((s) => s.id);
  const count = jobIds.length;
  const jobWord = `${count} job${count === 1 ? "" : "s"}`;
  const label = ordered.length
    ? `${ordered.map((stage) => VERBS[stage]).join(" + ")} ${jobWord}`
    : "Choose a stage";

  const toggle = (stage: RedoStage, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(stage);
        // Fresh text with stale criteria is a trap, so re-pull pre-ticks
        // re-extract. It stays untickable afterwards.
        if (stage === "pull") next.add("extract");
      } else {
        next.delete(stage);
      }
      return next;
    });

  const submit = async () => {
    setIsLaunching(true);
    try {
      if (await onLaunch(jobIds, ordered, deep)) onOpenChange(false);
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>Redo pipeline stages</DialogTitle>
        <DialogDescription>
          Re-run any stage on {jobWord}, whatever their status. Existing resume
          versions and PDFs are kept.
        </DialogDescription>
      </DialogHeader>

      <FieldSet>
        <FieldLegend variant="label">Stages</FieldLegend>
        <FieldGroup>
          {STAGES.map((stage) => {
            const inputId = `redo-stage-${stage.id}`;
            return (
              <Field key={stage.id} orientation="horizontal">
                <Checkbox
                  id={inputId}
                  checked={selected.has(stage.id)}
                  disabled={isLaunching}
                  onCheckedChange={(checked) => toggle(stage.id, Boolean(checked))}
                />
                <div>
                  <FieldLabel htmlFor={inputId}>{stage.label}</FieldLabel>
                  <FieldDescription>{stage.hint}</FieldDescription>
                </div>
              </Field>
            );
          })}
        </FieldGroup>
      </FieldSet>

      {selected.has("tailor") && (
        <Field orientation="horizontal">
          <Switch
            id="redo-deep-review"
            checked={deep}
            disabled={isLaunching}
            onCheckedChange={setDeep}
          />
          <div>
            <FieldLabel htmlFor="redo-deep-review">Deep review</FieldLabel>
            <FieldDescription>Full review panel; roughly 3–6× slower.</FieldDescription>
          </div>
        </Field>
      )}

      <DialogFooter>
        <Button
          variant="outline"
          disabled={isLaunching}
          onClick={() => onOpenChange(false)}
        >
          Cancel
        </Button>
        <Button disabled={!ordered.length || isLaunching} onClick={submit}>
          {isLaunching && <Spinner data-icon="inline-start" />}
          {isLaunching ? "Starting…" : label}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
