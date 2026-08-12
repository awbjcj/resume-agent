import { useState, type FormEvent } from "react";
import { Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

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
import { Field, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import type { RunRecord } from "@/lib/runs/store";

import {
  CareerLabResumeVersionPicker,
  CareerLabSkillPicker,
} from "./CareerLabContextRail";
import {
  useCareerLabSkills,
  useStartCareerLab,
  type CareerLabSkillName,
} from "./use-career-lab";

type ResumeVersion = components["schemas"]["ResumeVersionOut"];

export function CareerLabSetupDialog({
  jobId,
  jobLabel,
  versions,
  open,
  onOpenChange,
}: {
  jobId: number;
  jobLabel: string;
  versions: ResumeVersion[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const skills = useCareerLabSkills();
  const start = useStartCareerLab();
  const [message, setMessage] = useState("");
  const [skill, setSkill] = useState("");
  const [resumeVersionId, setResumeVersionId] = useState(0);
  const [includeProfile, setIncludeProfile] = useState(true);
  const [notice, setNotice] = useState("");

  const onDone = (completed: RunRecord) => {
    if (completed.status !== "succeeded") return;
    const result = completed.result as {
      sessionId?: string;
      needsSelection?: boolean;
      route?: { reason?: string };
    } | null;
    if (result?.sessionId) {
      navigate(`/career-lab?session=${result.sessionId}`);
      return;
    }
    // Career Lab could not route the request to one skill, so no session was
    // created and there is nothing to open. Reopen with the request intact and
    // ask for the skill explicitly — the same recovery the Career Lab page does.
    //
    // The toast is not decoration: the dialog closes as soon as the run is
    // accepted, and it lives inside a Tabs panel that unmounts when the user
    // switches tab or closes the modal. If that happened, `setNotice` reaches a
    // dead component and the run succeeded, so the mutation's own failure toast
    // never fires either — a paid-for request would vanish with no feedback at
    // all. The toast is the one part of this recovery that survives unmounting.
    if (result?.needsSelection) {
      const reason =
        result.route?.reason ??
        "Career Lab could not tell which skill this needs. Choose one and start again.";
      toast.warning(reason);
      setNotice(reason);
      onOpenChange(true);
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const request = message.trim();
    if (!request) return;
    setNotice("");
    try {
      await start.mutateAsync({
        message: request,
        goal: request,
        skill: skill ? (skill as CareerLabSkillName) : undefined,
        context: {
          jobId,
          ...(resumeVersionId ? { resumeVersionId } : {}),
          ...(includeProfile ? { profileSnapshot: "current" as const } : {}),
          offerApplicationIds: [],
        },
        onDone,
      });
      // The run is accepted. Progress belongs in the global run surface rather
      // than a dialog the user has to sit in front of.
      onOpenChange(false);
    } catch {
      // useStartCareerLab owns the error toast; leaving the dialog open lets the
      // user retry without retyping their request.
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="border-b bg-muted/35 p-5 pr-14 sm:p-6 sm:pr-16">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/15">
              <Sparkles className="size-5" aria-hidden="true" />
            </span>
            <div className="space-y-1.5">
              <DialogTitle className="text-lg leading-tight">
                Ask Career Lab about this role
              </DialogTitle>
              <DialogDescription className="leading-6">
                Start a thread anchored to {jobLabel}. The job description travels
                with every turn, and the whole conversation is kept here.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)}>
          <div className="space-y-5 p-5 sm:p-6">
            {notice ? (
              <p
                className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
                role="alert"
              >
                {notice}
              </p>
            ) : null}
            <Field>
              <FieldLabel htmlFor="career-lab-request">
                What do you want help with?
              </FieldLabel>
              <Textarea
                id="career-lab-request"
                rows={4}
                maxLength={100000}
                value={message}
                placeholder="For example: draft an answer to their “why this team” question."
                onChange={(event) => setMessage(event.target.value)}
              />
            </Field>
            <CareerLabSkillPicker
              skill={skill}
              setSkill={setSkill}
              skills={skills}
              id="career-lab-job-skill"
            />
            <CareerLabResumeVersionPicker
              id="career-lab-job-version"
              versions={versions}
              value={resumeVersionId || undefined}
              onChange={(value) => setResumeVersionId(value ?? 0)}
              emptyLabel={
                versions.length ? "No resume version" : "No tailored resume yet"
              }
              disabled={versions.length === 0}
            />
            <label className="flex items-start gap-3 rounded-lg border bg-muted/20 p-3 text-sm">
              <Checkbox
                checked={includeProfile}
                onCheckedChange={(checked) => setIncludeProfile(Boolean(checked))}
                aria-label="Include current profile"
              />
              <span>
                <span className="block font-medium">Include your profile</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  Lets Career Lab answer in terms of your own experience.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter className="mx-0 mb-0 rounded-none px-5 py-4 sm:px-6">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={start.isPending || !message.trim()}>
              {start.isPending ? <Spinner data-icon="inline-start" /> : null}
              {start.isPending ? "Starting…" : "Start thread"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
