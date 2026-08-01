import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import type { RunRecord } from "@/lib/runs/store";

import { useStartInterview } from "./use-interview";

type ResumeVersion = components["schemas"]["ResumeVersionOut"];

const STAGES = [
  { value: "recruiter_screen", label: "Recruiter screen" },
  { value: "hiring_manager", label: "Hiring manager" },
  { value: "technical", label: "Technical" },
  { value: "behavioral", label: "Behavioral" },
];
const DEMEANORS = [
  { value: "warm", label: "Warm" },
  { value: "neutral", label: "Neutral" },
  { value: "stress", label: "Stress" },
];
const DIFFICULTIES = [
  { value: "easy", label: "Easy" },
  { value: "standard", label: "Standard" },
  { value: "hard", label: "Hard" },
];
// A Select rather than a number Input: the range is small and bounded, and it
// keeps every control in this form the same primitive — so they share a height
// and a type scale instead of an `h-10` input towering over `h-9` triggers.
const QUESTION_COUNTS = Array.from({ length: 9 }, (_, index) => {
  const count = index + 4;
  return { value: String(count), label: String(count) };
});

export function InterviewSetupDialog({
  jobId,
  versions,
  open,
  onOpenChange,
}: {
  jobId: number;
  versions: ResumeVersion[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const start = useStartInterview();
  const newestVersionId = useMemo(
    () => versions.reduce((newest, version) => Math.max(newest, version.id), 0),
    [versions],
  );
  const [stage, setStage] = useState("hiring_manager");
  const [demeanor, setDemeanor] = useState("neutral");
  const [difficulty, setDifficulty] = useState("standard");
  const [questionCount, setQuestionCount] = useState(8);
  const [resumeVersionId, setResumeVersionId] = useState(newestVersionId);
  const [extra, setExtra] = useState("");

  const submit = async () => {
    await start.mutateAsync({
      jobId,
      resumeVersionId: resumeVersionId || newestVersionId,
      style: { stage, demeanor, difficulty, questionCount, extra },
      onDone: (completed: RunRecord) => {
        if (completed.status === "succeeded") {
          const result = completed.result as { sessionId?: string } | null;
          if (result?.sessionId) {
            onOpenChange(false);
            navigate(`/interview?session=${result.sessionId}`);
          }
        }
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Set up your mock interview</DialogTitle>
          <DialogDescription>
            Choose the interviewer's style. Questions are grounded in this job and your selected resume.
          </DialogDescription>
        </DialogHeader>
        {/* Every control is a `compact` (h-9) Select or a Textarea, so the two
            columns stay on a single baseline grid. */}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="interview-stage">Stage</FieldLabel>
            <Select items={STAGES} value={stage} onValueChange={(v) => setStage(v ?? "hiring_manager")}>
              <SelectTrigger id="interview-stage" size="compact" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {STAGES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-demeanor">Demeanor</FieldLabel>
            <Select items={DEMEANORS} value={demeanor} onValueChange={(v) => setDemeanor(v ?? "neutral")}>
              <SelectTrigger id="interview-demeanor" size="compact" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DEMEANORS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-difficulty">Difficulty</FieldLabel>
            <Select items={DIFFICULTIES} value={difficulty} onValueChange={(v) => setDifficulty(v ?? "standard")}>
              <SelectTrigger id="interview-difficulty" size="compact" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DIFFICULTIES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-count">Questions</FieldLabel>
            <Select
              items={QUESTION_COUNTS}
              value={String(questionCount)}
              onValueChange={(v) => setQuestionCount(Number(v) || 8)}
            >
              <SelectTrigger id="interview-count" size="compact" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {QUESTION_COUNTS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field className="sm:col-span-2">
            <FieldLabel htmlFor="interview-version">Resume version</FieldLabel>
            <Select
              items={versions.map((version) => ({
                value: String(version.id),
                label: `${new Date(version.createdAt).toLocaleDateString()} · ${version.origin}`,
              }))}
              value={String(resumeVersionId || newestVersionId)}
              onValueChange={(v) => setResumeVersionId(Number(v))}
            >
              <SelectTrigger id="interview-version" size="compact" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {versions.map((version) => (
                  <SelectItem key={version.id} value={String(version.id)}>
                    {new Date(version.createdAt).toLocaleDateString()} · {version.origin}
                    {version.reviewScore != null ? ` · ${version.reviewScore}/100` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field className="sm:col-span-2">
            <FieldLabel htmlFor="interview-extra">Anything specific to cover? (optional)</FieldLabel>
            <Textarea
              id="interview-extra"
              rows={3}
              maxLength={2000}
              value={extra}
              placeholder="e.g. Ask about system design and Kubernetes."
              onChange={(event) => setExtra(event.target.value)}
            />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={start.isPending || !newestVersionId} onClick={() => void submit()}>
            {start.isPending ? <Spinner data-icon="inline-start" /> : null}
            Start interview
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
