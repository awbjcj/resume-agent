import { useRef, useState } from "react";
import { Bot, Clock3, MessagesSquare, Plus, SquareCheckBig } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
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
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Progress, ProgressLabel } from "@/components/ui/progress";
import { useChatStream } from "@/lib/chat/useChatStream";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";

import { DebriefCard } from "./DebriefCard";
import { NewInterviewDialog } from "./NewInterviewDialog";
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

  const [newOpen, setNewOpen] = useState(false);
  const [composer, setComposer] = useState("");
  const [lastMessage, setLastMessage] = useState("");
  const [runError, setRunError] = useState("");
  const [streamRunId, setStreamRunId] = useState<string | null>(null);
  const [streamBaseline, setStreamBaseline] = useState(0);
  const [suppressedRunId, setSuppressedRunId] = useState<string | null>(null);
  const ignoredRuns = useRef(new Set<string>());
  const recoveredRunId = useRunStore((state) => {
    const run = Object.values(state.runs).find(
      (candidate) =>
        candidate.kind === "mock-interview-turn" &&
        ["queued", "running", "cancelling"].includes(candidate.status) &&
        candidate.meta?.sessionId === displayedSessionId,
    );
    return run?.runId ?? null;
  });
  const recoveredBaseline = useRunStore((state) => {
    const run = Object.values(state.runs).find(
      (candidate) =>
        candidate.kind === "mock-interview-turn" &&
        ["queued", "running", "cancelling"].includes(candidate.status) &&
        candidate.meta?.sessionId === displayedSessionId,
    );
    return typeof run?.meta?.turnCount === "number" ? run.meta.turnCount : 0;
  });
  const attachedRunId =
    streamRunId ??
    (recoveredRunId && recoveredRunId !== suppressedRunId ? recoveredRunId : null);
  const attachedBaseline = streamRunId ? streamBaseline : recoveredBaseline;
  const stream = useChatStream(attachedRunId);

  const active = session.data;
  const sending = send.isPending || Boolean(
    attachedRunId && stream.status !== "done" && stream.status !== "error",
  );
  const ending = end.isPending;

  const sendMessage = async (message = composer.trim()) => {
    if (!active || !message || sending) return;
    setLastMessage(message);
    setRunError("");
    setStreamBaseline(active.turns?.length ?? 0);
    setSuppressedRunId(null);
    stream.reset();
    try {
      const launched = await send.mutateAsync({
        sessionId: active.sessionId,
        message,
        onDone: (completed: RunRecord) => {
          if (ignoredRuns.current.delete(completed.runId)) return;
          if (completed.status === "succeeded") {
            setComposer((current) => (current.trim() === message ? "" : current));
          } else {
            setRunError(completed.error ?? "Answer failed");
          }
        },
      });
      setStreamRunId(launched.runId);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Answer failed");
    }
  };

  const stopAnswer = () => {
    if (attachedRunId) ignoredRuns.current.add(attachedRunId);
    setSuppressedRunId(attachedRunId);
    stream.stop();
    setStreamRunId(null);
    setRunError("");
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
    // The hub is now a top-level destination, so first-time arrivals land here
    // with nothing selected — the empty state has to be able to start a run.
    const noSessions = !sessions.isPending && (sessions.data?.sessions?.length ?? 0) === 0;
    return (
      <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
        <SessionsRail selectedId={displayedSessionId} />
        <Card className="min-h-[28rem] min-w-0 flex-1 bg-card/90">
          <CardContent className="flex min-h-[28rem] items-center justify-center py-14">
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon"><MessagesSquare aria-hidden="true" /></EmptyMedia>
                <EmptyTitle>{noSessions ? "No mock interviews yet" : "No interview selected"}</EmptyTitle>
                <EmptyDescription>
                  {noSessions
                    ? "Practise against a job you have already tailored a resume for, then get a scored debrief."
                    : "Select a session or start a new interview."}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button onClick={() => setNewOpen(true)}><Plus aria-hidden="true" />Start a mock interview</Button>
              </EmptyContent>
            </Empty>
          </CardContent>
        </Card>
        <NewInterviewDialog open={newOpen} onOpenChange={setNewOpen} />
      </div>
    );
  }

  const ended = active.status === "ended";
  const canAnswer = active.status === "active" && !active.concluded;
  const chatMessages: ChatThreadMessage[] = (active.turns ?? []).map((turn, index) => {
    const notice = (turn as typeof turn & { notice?: string }).notice;
    return {
      id: `${turn.at}-${index}`,
      role: turn.role === "interviewer" ? "assistant" : "user",
      parts: [
        { kind: "text" as const, text: turn.text },
        ...(notice ? [{ kind: "notice" as const, message: notice }] : []),
      ],
    };
  });
  const durableAdvanced = (active.turns?.length ?? 0) > attachedBaseline;
  const streamingParts = attachedRunId && !durableAdvanced ? stream.parts : null;
  const visibleError = stream.error || runError;

  return (
    <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
      <SessionsRail selectedId={displayedSessionId} />
      <main className="flex min-w-0 flex-1 flex-col gap-6">
        <header className="rounded-2xl bg-card/90 p-5 shadow-card ring-1 ring-foreground/10 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Mock interview</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-[-0.025em] sm:text-3xl">
                {active.company || "Mock interview"} — {active.title}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <Badge variant="secondary" className="capitalize">{active.style.stage.replace("_", " ")}</Badge>
                <Badge variant="outline" className="capitalize">{active.style.demeanor}</Badge>
                <Badge variant="outline" className="capitalize">{active.style.difficulty}</Badge>
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
          </div>
          <Progress
            className="mt-5 gap-2"
            value={active.progress.total ? Math.round((active.progress.asked / active.progress.total) * 100) : 0}
          >
            <ProgressLabel>Interview progress</ProgressLabel>
            <span className="ml-auto text-sm tabular-nums text-muted-foreground">
              Question {active.progress.asked} of {active.progress.total}
            </span>
          </Progress>
        </header>

      {visibleError ? (
        <Alert variant="destructive">
          <AlertTitle>Interview error</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span className="flex-1">{visibleError}</span>
            {canAnswer && lastMessage ? (
              <Button size="sm" variant="outline" onClick={() => { stream.reset(); void sendMessage(lastMessage); }}>Retry</Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      <Card className="min-w-0 overflow-hidden rounded-2xl">
        <CardHeader className="border-b bg-muted/25 py-1">
          <CardTitle className="flex items-center gap-2 text-lg">
            <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Bot className="size-5" aria-hidden="true" /></span>
            Live interview
          </CardTitle>
          <CardDescription className="flex items-center gap-2 text-sm">
            <Clock3 className="size-4" aria-hidden="true" />Started {new Date(active.startedAt).toLocaleString()}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex h-[min(62vh,46rem)] min-h-[26rem] flex-col gap-4 p-4 sm:min-h-[32rem] sm:p-8">
            <ChatThread
              messages={chatMessages}
              streaming={streamingParts}
              streamingActive={stream.status === "streaming"}
              showReasoning={false}
            />
            {sending && !stream.parts.length ? (
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Spinner />
                <span>The interviewer is thinking…</span>
              </div>
            ) : null}
          </div>

          {canAnswer ? (
            <div className="border-t bg-card/95 p-4 sm:p-6">
              <ChatComposer
                value={composer}
                onChange={setComposer}
                onSend={() => void sendMessage()}
                onStop={stopAnswer}
                busy={sending}
                settling={stream.status === "settled"}
                ariaLabel="Your answer"
                placeholder="Answer as you would in a real interview…"
              />
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
