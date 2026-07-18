import { MessagesSquare } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

import { useEndInterview, useInterviewSessions } from "./use-interview";

/**
 * App-wide re-entry for the single active mock interview. An active session is a
 * global singleton that also blocks starting new interviews, so it needs an
 * affordance reachable from any page — the per-job Interview tab is not enough.
 * Hidden on /interview itself, where the page already owns Resume + End.
 */
export function ActiveInterviewBanner() {
  const location = useLocation();
  const sessions = useInterviewSessions();
  const end = useEndInterview();
  const active = sessions.data?.sessions?.find((s) => s.status === "active");

  if (!active || location.pathname === "/interview") return null;

  const label = [active.company, active.title].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-amber-500/30 bg-amber-500/10 px-5 py-2.5 text-sm md:px-8 lg:px-10">
      <MessagesSquare className="size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
      <span className="min-w-0">
        <span className="font-medium">Mock interview in progress</span>
        {label ? <span className="text-muted-foreground"> — {label}</span> : null}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Button size="sm" render={<Link to={`/interview?session=${active.sessionId}`}>Resume</Link>} />
        <AlertDialog>
          <AlertDialogTrigger
            render={
              <Button size="sm" variant="outline" disabled={end.isPending}>
                {end.isPending ? <Spinner data-icon="inline-start" /> : null}End
              </Button>
            }
          />
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>End the interview now?</AlertDialogTitle>
              <AlertDialogDescription>
                The interviewer will stop and your coach will score the questions asked so far.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep going</AlertDialogCancel>
              <AlertDialogAction
                disabled={end.isPending}
                onClick={() => void end.mutateAsync({ sessionId: active.sessionId })}
              >
                End interview
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}
