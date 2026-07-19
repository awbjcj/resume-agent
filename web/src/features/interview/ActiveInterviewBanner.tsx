import { MessagesSquare } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useInterviewSessions } from "./use-interview";

/**
 * App-wide re-entry for every active mock interview. Per-session controls live
 * on the interview hub itself.
 */
export function ActiveInterviewBanner() {
  const location = useLocation();
  const sessions = useInterviewSessions();
  const active = (sessions.data?.sessions ?? []).filter((session) => session.status === "active");

  if (!active.length || location.pathname === "/interview") return null;

  const single = active.length === 1 ? active[0] : null;
  const label = single ? [single.company, single.title].filter(Boolean).join(" · ") : `${active.length} mock interviews in progress`;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-primary/20 bg-primary/5 px-5 py-2.5 text-sm md:px-8 lg:px-10">
      <MessagesSquare className="shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0">
        <span className="font-medium">{single ? "Mock interview in progress" : label}</span>
        {single && label ? <span className="text-muted-foreground"> — {label}</span> : null}
      </span>
      <Link className={cn(buttonVariants({ size: "sm" }), "ml-auto")} to={single ? `/interview?session=${single.sessionId}` : "/interview"}>{single ? "Resume" : "Open interviews"}</Link>
    </div>
  );
}
