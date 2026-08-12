import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

import { CareerLabSetupDialog } from "./CareerLabSetupDialog";
import { useCareerLabSessions } from "./use-career-lab";

type ResumeVersion = components["schemas"]["ResumeVersionOut"];

export function CareerLabTab({
  jobId,
  jobLabel,
  versions,
}: {
  jobId: number;
  jobLabel: string;
  versions: ResumeVersion[];
}) {
  const [open, setOpen] = useState(false);
  const sessions = useCareerLabSessions({ jobId });
  // The endpoint orders open threads first, then newest — so the open thread is
  // on this page whatever the count, and `activeRow` is trustworthy here.
  const rows = sessions.data?.sessions ?? [];
  const activeRow = rows.find((row) => row.status === "active");

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Career Lab
        </h3>
        <p className="text-sm text-muted-foreground">
          Ask about this role with the job description in context — application
          answers, outreach, negotiation prep — and keep every thread here.
        </p>
        {activeRow ? (
          <p className="text-sm text-muted-foreground">
            A thread for this job is open — continue it from the list below.
          </p>
        ) : (
          <Button onClick={() => setOpen(true)}>
            <Sparkles aria-hidden="true" />
            Start a Career Lab thread
          </Button>
        )}
      </div>

      {rows.length ? (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li
              key={row.sessionId}
              className="flex items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3"
            >
              <Link
                to={`/career-lab?session=${row.sessionId}`}
                className="min-w-0 flex-1 hover:underline"
              >
                <span className="block truncate text-sm font-medium">
                  {row.title || row.goal || "Untitled thread"}
                </span>
                <span className="text-xs text-muted-foreground">
                  {row.status === "ended" ? "Completed" : "Open"} ·{" "}
                  {row.turnCount} turn{row.turnCount === 1 ? "" : "s"} ·{" "}
                  {new Date(row.startedAt).toLocaleDateString()}
                </span>
              </Link>
              {row.status === "ended" ? null : (
                <Badge variant="outline">Continue</Badge>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {/* Rendered unconditionally: it shows nothing while closed, `open` can
          only be set by the button above (itself withdrawn once a thread is
          open), and staying mounted is what lets the dialog's skill-selection
          recovery survive a thread appearing mid-run. */}
      <CareerLabSetupDialog
        jobId={jobId}
        jobLabel={jobLabel}
        versions={versions}
        open={open}
        onOpenChange={setOpen}
      />
    </div>
  );
}
