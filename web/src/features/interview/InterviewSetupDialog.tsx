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
import { Input } from "@/components/ui/input";
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="interview-stage">Stage</FieldLabel>
            <Select items={STAGES} value={stage} onValueChange={(v) => setStage(v ?? "hiring_manager")}>
              <SelectTrigger id="interview-stage" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {STAGES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-demeanor">Demeanor</FieldLabel>
            <Select items={DEMEANORS} value={demeanor} onValueChange={(v) => setDemeanor(v ?? "neutral")}>
              <SelectTrigger id="interview-demeanor" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DEMEANORS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-difficulty">Difficulty</FieldLabel>
            <Select items={DIFFICULTIES} value={difficulty} onValueChange={(v) => setDifficulty(v ?? "standard")}>
              <SelectTrigger id="interview-difficulty" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DIFFICULTIES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="interview-count">Questions</FieldLabel>
            <Input
              id="interview-count"
              type="number"
              min={4}
              max={12}
              value={questionCount}
              onChange={(event) =>
                setQuestionCount(Math.min(12, Math.max(4, Number(event.target.value) || 8)))
              }
            />
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
              <SelectTrigger id="interview-version" className="w-full"><SelectValue /></SelectTrigger>
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
