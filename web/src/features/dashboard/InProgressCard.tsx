import { Bot, MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { timeAgo } from "./time-ago";
import type { DashboardSummary } from "./use-dashboard-summary";

export function InProgressCard({ summary }: { summary: DashboardSummary }) {
  const interviews = summary.activeInterviews ?? [];
  const coach = summary.activeCoachSession;
  return <Card><CardHeader><CardTitle className="text-base">In progress</CardTitle></CardHeader><CardContent>
    {!interviews.length && !coach ? <p className="text-sm text-muted-foreground">Nothing in progress — start a mock interview or a coaching session.</p> : <ul className="flex flex-col gap-3">
      {interviews.map((row) => { const label = [row.company, row.title].filter(Boolean).join(" · ") || "Mock interview"; return <li key={row.sessionId} className="flex items-center gap-3"><MessagesSquare className="shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{label}</span><span className="text-xs text-muted-foreground">Question {row.askedCount} of {row.questionCount} · started {timeAgo(Date.parse(row.startedAt))}</span></div><Link aria-label={`Resume ${label}`} className="text-sm font-medium text-primary hover:underline" to={`/interview?session=${row.sessionId}`}>Resume</Link></li>; })}
      {coach ? <li className="flex items-center gap-3"><Bot className="shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0 flex-1"><span className="block text-sm font-medium">Profile coaching in progress</span><span className="text-xs text-muted-foreground">{coach.savedNoteCount} note{coach.savedNoteCount === 1 ? "" : "s"} saved · started {timeAgo(Date.parse(coach.startedAt))}</span></div><Link aria-label="Resume profile coaching" className="text-sm font-medium text-primary hover:underline" to="/coach">Resume</Link></li> : null}
    </ul>}
  </CardContent></Card>;
}
