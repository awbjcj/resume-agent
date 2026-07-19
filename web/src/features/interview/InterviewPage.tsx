import { useState } from "react";
import { Bot, Clock3, MessagesSquare, Send, SquareCheckBig, UserRound } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { TranscribeButton } from "@/components/TranscribeButton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { RunRecord } from "@/lib/runs/store";
import { cn } from "@/lib/utils";

import { DebriefCard } from "./DebriefCard";
import { SessionsRail } from "./SessionsRail";
import {
  useEndInterview,
  useInterviewSession,
  useInterviewSessions,
  useSendInterviewAnswer,
} from "./use-interview";

export function InterviewPage() {
  const [params] = useSearchParams();
  const sessionParam = params.get("session");
  const sessions = useInterviewSessions();
  const activeSummary = sessions.data?.sessions?.find((s) => s.status === "active");
  const displayedSessionId = sessionParam ?? activeSummary?.sessionId ?? null;
  const session = useInterviewSession(displayedSessionId);
  const send = useSendInterviewAnswer();
  const end = useEndInterview();

  const [composer, setComposer] = useState("");
  const [lastMessage, setLastMessage] = useState("");
  const [runError, setRunError] = useState("");

  const active = session.data;
  const sending = send.isPending;
  const ending = end.isPending;

  const sendMessage = async (message = composer.trim()) => {
    if (!active || !message || sending) return;
    setLastMessage(message);
    setRunError("");
    try {
      await send.mutateAsync({
        sessionId: active.sessionId,
        message,
        onDone: (completed: RunRecord) => {
          if (completed.status === "succeeded") {
            setComposer((current) => (current.trim() === message ? "" : current));
          } else {
            setRunError(completed.error ?? "Answer failed");
          }
        },
      });
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Answer failed");
    }
  };

  const endInterview = async () => {
    if (!active) return;
    setRunError("");
    try {
      await end.mutateAsync({
        sessionId: active.sessionId,
        onDone: (completed: RunRecord) => {
          if (completed.status !== "succeeded") {
            setRunError(completed.error ?? "Could not end interview");
          }
        },
      });
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Could not end interview");
    }
  };

  if (session.isLoading && displayedSessionId) {
    return (
      <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
        <SessionsRail selectedId={displayedSessionId} />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-[32rem] w-full" />
        </div>
      </div>
    );
  }

  if (!active) {
    return (
      <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
        <SessionsRail selectedId={displayedSessionId} />
        <Card className="min-h-[28rem] min-w-0 flex-1 border-dashed">
          <CardContent className="flex min-h-[28rem] items-center justify-center py-14">
            <Empty><EmptyHeader><EmptyMedia variant="icon"><MessagesSquare aria-hidden="true" /></EmptyMedia><EmptyTitle>No interview selected</EmptyTitle><EmptyDescription>Select a session or start a new interview.</EmptyDescription></EmptyHeader></Empty>
          </CardContent>
        </Card>
      </div>
    );
  }

  const ended = active.status === "ended";
  const canAnswer = active.status === "active" && !active.concluded;

  return (
    <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
      <SessionsRail selectedId={displayedSessionId} />
      <main className="flex min-w-0 flex-1 flex-col gap-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {active.company || "Mock interview"} — {active.title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="outline">{active.style.stage.replace("_", " ")}</Badge>
            <Badge variant="outline">{active.style.demeanor}</Badge>
            <Badge variant="outline">{active.style.difficulty}</Badge>
            <span>Question {active.progress.asked} of {active.progress.total}</span>
          </div>
        </div>
        {active.status === "active" ? (
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="outline"><SquareCheckBig aria-hidden="true" />End interview</Button>} />
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>End the interview now?</AlertDialogTitle>
                <AlertDialogDescription>
                  The interviewer will stop and your coach will score the questions asked so far.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep going</AlertDialogCancel>
                <AlertDialogAction disabled={ending} onClick={() => void endInterview()}>
                  {ending ? <Spinner data-icon="inline-start" /> : null}End interview
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null}
      </header>

      {runError ? (
        <Alert variant="destructive">
          <AlertTitle>Interview error</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span className="flex-1">{runError}</span>
            {canAnswer && lastMessage ? (
              <Button size="sm" variant="outline" onClick={() => void sendMessage(lastMessage)}>Retry</Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      <Card className="min-w-0 overflow-hidden">
        <CardHeader className="border-b bg-muted/20">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Bot className="size-5 text-primary" aria-hidden="true" />Interview
          </CardTitle>
          <CardDescription className="flex items-center gap-2 text-sm">
            <Clock3 className="size-4" aria-hidden="true" />Started {new Date(active.startedAt).toLocaleString()}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-[min(64vh,48rem)] min-h-[32rem]">
            <div className="flex flex-col gap-6 p-5 sm:p-8">
              {(active.turns ?? []).map((turn, index) => (
                <div key={`${turn.at}-${index}`} className={cn("flex items-start gap-3", turn.role === "candidate" && "flex-row-reverse")}>
                  <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-full", turn.role === "interviewer" ? "bg-primary/10 text-primary" : "bg-primary text-primary-foreground")}>
                    {turn.role === "interviewer" ? <Bot className="size-5" aria-hidden="true" /> : <UserRound className="size-5" aria-hidden="true" />}
                  </div>
                  <div className={cn("max-w-[88%] rounded-2xl px-5 py-4 text-base leading-7 sm:max-w-[82%]", turn.role === "interviewer" ? "rounded-tl-sm bg-muted" : "rounded-tr-sm bg-primary text-primary-foreground")}>
                    {turn.text}
                  </div>
                </div>
              ))}
              {sending ? (
                <div className="flex items-center gap-3 text-base text-muted-foreground"><Spinner /><span>The interviewer is thinking…</span></div>
              ) : null}
            </div>
          </ScrollArea>

          {canAnswer ? (
            <div className="border-t bg-card p-5 sm:p-6">
              <Field>
                <FieldLabel htmlFor="interview-composer">Your answer</FieldLabel>
                <Textarea
                  id="interview-composer"
                  aria-label="Your answer"
                  rows={4}
                  className="text-base leading-7"
                  value={composer}
                  disabled={sending}
                  placeholder="Answer as you would in a real interview…"
                  onChange={(event) => setComposer(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                />
                <FieldDescription className="flex items-center justify-between gap-3">
                  <span>Press Enter to send, Shift + Enter for a new line.</span>
                  <span className="flex items-center gap-2">
                    <TranscribeButton
                      disabled={sending}
                      onText={(text) => setComposer((prev) => (prev ? `${prev} ${text}` : text))}
                    />
                    <Button aria-label="Send answer" disabled={!composer.trim() || sending} onClick={() => void sendMessage()}>
                      {sending ? <Spinner data-icon="inline-start" /> : <Send aria-hidden="true" />}Send
                    </Button>
                  </span>
                </FieldDescription>
              </Field>
            </div>
          ) : active.concluded && !ended ? (
            <div className="flex flex-col items-center gap-3 border-t bg-card p-6 text-center">
              <p className="text-sm text-muted-foreground">The interview is complete. Get your scored debrief.</p>
              <Button disabled={ending} onClick={() => void endInterview()}>
                {ending ? <Spinner data-icon="inline-start" /> : <SquareCheckBig aria-hidden="true" />}Get your debrief
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {ended && active.debrief ? <DebriefCard debrief={active.debrief} plan={active.plan ?? []} /> : null}
      </main>
    </div>
  );
}
