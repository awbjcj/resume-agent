import { useState } from "react";
import { MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

import { InterviewSetupDialog } from "./InterviewSetupDialog";
import { useInterviewSessions } from "./use-interview";

type ResumeVersion = components["schemas"]["ResumeVersionOut"];

export function InterviewTab({
  jobId,
  versions,
  hasJd,
}: {
  jobId: number;
  versions: ResumeVersion[];
  hasJd: boolean;
}) {
  const [open, setOpen] = useState(false);
  const sessions = useInterviewSessions(jobId);
  const canStart = versions.length > 0 && hasJd;
  const rows = sessions.data?.sessions ?? [];

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Mock interview
        </h3>
        <p className="text-sm text-muted-foreground">
          Rehearse against this job description and one of your tailored resumes, then get a scored debrief.
        </p>
        <Button disabled={!canStart} onClick={() => setOpen(true)}>
          <MessagesSquare aria-hidden="true" />Start mock interview
        </Button>
        {!canStart ? (
          <p className="text-xs text-muted-foreground">
            {hasJd ? "Tailor a resume first to run a mock interview." : "This job has no description to interview against."}
          </p>
        ) : null}
      </div>

      {rows.length ? (
        <ul className="space-y-2">
          {rows.map((row) => {
            const meta = (
              <>
                <span className="block text-sm font-medium">
                  {new Date(row.startedAt).toLocaleDateString()}
                </span>
                <span className="text-xs text-muted-foreground">
                  {row.status === "ended" ? "Completed" : "In progress"} · {row.askedCount}/{row.questionCount} questions
                </span>
              </>
            );
            return (
              <li key={row.sessionId} className="flex items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3">
                <Link to={`/interview?session=${row.sessionId}`} className="min-w-0 flex-1 hover:underline">
                  {meta}
                </Link>
                {row.status !== "ended" ? (
                  <Badge variant="outline">Resume</Badge>
                ) : row.overallScore != null ? (
                  <Badge variant="secondary">{row.overallScore}/5</Badge>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {canStart ? (
        <InterviewSetupDialog jobId={jobId} versions={versions} open={open} onOpenChange={setOpen} />
      ) : null}
    </div>
  );
}
