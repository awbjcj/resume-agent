import { useState } from "react";
import { Bot, MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { timeAgo } from "./time-ago";
import type { DashboardSummary } from "./use-dashboard-summary";

export function InProgressCard({ summary }: { summary: DashboardSummary }) {
  const { t, i18n } = useTranslation();
  const [now] = useState(Date.now);
  const interviews = summary.activeInterviews ?? [];
  const coach = summary.activeCoachSession;
  return <Card><CardHeader><CardTitle className="text-base">{t("dashboard.inProgress")}</CardTitle></CardHeader><CardContent>
    {!interviews.length && !coach ? <p className="text-sm text-muted-foreground">{t("dashboard.nothingInProgress")}</p> : <ul className="flex flex-col gap-3">
      {interviews.map((row) => { const label = [row.company, row.title].filter(Boolean).join(" · ") || t("dashboard.mockInterview"); return <li key={row.sessionId} className="flex items-center gap-3"><MessagesSquare className="shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{label}</span><span className="text-xs text-muted-foreground">{t("dashboard.interviewProgress", { asked: row.askedCount, total: row.questionCount, started: timeAgo(Date.parse(row.startedAt), now, i18n.resolvedLanguage) })}</span></div><Link aria-label={t("dashboard.resumeItem", { label })} className="text-sm font-medium text-primary hover:underline" to={`/interview?session=${row.sessionId}`}>{t("dashboard.resume")}</Link></li>; })}
      {coach ? <li className="flex items-center gap-3"><Bot className="shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0 flex-1"><span className="block text-sm font-medium">{t("dashboard.coachingInProgress")}</span><span className="text-xs text-muted-foreground">{t(coach.savedNoteCount === 1 ? "dashboard.coachingProgress_one" : "dashboard.coachingProgress_other", { count: coach.savedNoteCount, started: timeAgo(Date.parse(coach.startedAt), now, i18n.resolvedLanguage) })}</span></div><Link aria-label={t("dashboard.resumeCoaching")} className="text-sm font-medium text-primary hover:underline" to="/coach">{t("dashboard.resume")}</Link></li> : null}
    </ul>}
  </CardContent></Card>;
}
