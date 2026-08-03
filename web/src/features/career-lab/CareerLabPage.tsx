import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, FileText, ListChecks, MessageCircleMore, Sparkles, SquareCheckBig } from "lucide-react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatSessionHistory, type ChatSessionHistoryItem } from "@/components/chat/ChatSessionHistory";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
import { GuidedWorkspaceHeader } from "@/components/chat/GuidedWorkspaceHeader";
import { CHAT_PAGE_WIDTH, CHAT_SURFACE_HEIGHT } from "@/components/chat/layout";
import { WorkspaceEmptyState } from "@/components/chat/WorkspaceEmptyState";
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useChatStream } from "@/lib/chat/useChatStream";
import type { RunRecord } from "@/lib/runs/store";
import { cn } from "@/lib/utils";

import { CareerLabContextRail, CareerLabSkillPicker } from "./CareerLabContextRail";
import {
  useArchiveCareerLabSession,
  useCareerLabRecoveredRun,
  useCareerLabSession,
  useCareerLabSessions,
  useCareerLabSkills,
  useDeleteCareerLabSession,
  useEndCareerLab,
  useRenameCareerLabSession,
  useSendCareerLabMessage,
  useStartCareerLab,
  useUnarchiveCareerLabSession,
  type CareerLabContext,
} from "./use-career-lab";

export function CareerLabPage() {
  const [newOpen, setNewOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const sessions = useCareerLabSessions(showArchived);
  const skills = useCareerLabSkills();
  const activeSummary = sessions.data?.sessions?.find((row) => row.status === "active");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const displayedSessionId = selectedSessionId ?? activeSummary?.sessionId ?? null;
  const session = useCareerLabSession(displayedSessionId);
  const start = useStartCareerLab();
  const send = useSendCareerLabMessage();
  const end = useEndCareerLab();
  const archive = useArchiveCareerLabSession();
  const unarchive = useUnarchiveCareerLabSession();
  const remove = useDeleteCareerLabSession();
  const rename = useRenameCareerLabSession();
  const recoveredRun = useCareerLabRecoveredRun(displayedSessionId);
  const [streamRunId, setStreamRunId] = useState<string | null>(null);
  const [suppressedRunId, setSuppressedRunId] = useState<string | null>(null);
  const runId = streamRunId ?? (recoveredRun && recoveredRun.runId !== suppressedRunId ? recoveredRun.runId : null);
  const stream = useChatStream(runId);
  const [composer, setComposer] = useState("");
  const [skill, setSkill] = useState("");
  const [context, setContext] = useState<CareerLabContext>({ offerApplicationIds: [] });
  const [pending, setPending] = useState<{ text: string; baseline: number } | null>(null);
  const [runError, setRunError] = useState("");
  const [retryMessage, setRetryMessage] = useState("");
  const [selectionNotice, setSelectionNotice] = useState("");
  const [selectionExchange, setSelectionExchange] = useState<{
    userText: string;
    assistantText: string;
  } | null>(null);
  const skillRef = useRef<HTMLSelectElement>(null);
  const ignoredRuns = useRef(new Set<string>());
  const attachedRuns = useRef(new Set<string>());
  const completedBeforeAttach = useRef(new Set<string>());

  const attachRun = (nextRunId: string) => {
    if (completedBeforeAttach.current.delete(nextRunId)) return;
    attachedRuns.current.add(nextRunId);
    setStreamRunId(nextRunId);
  };

  const detachRun = (completedRunId: string) => {
    if (!attachedRuns.current.delete(completedRunId)) {
      completedBeforeAttach.current.add(completedRunId);
      return;
    }
    setStreamRunId((current) => (current === completedRunId ? null : current));
  };

  useEffect(() => {
    if (selectionNotice) skillRef.current?.focus();
  }, [selectionNotice]);

  const active = session.data;
  const sessionLoading = Boolean(displayedSessionId && session.isPending);
  const baseline = pending?.baseline ?? active?.turns?.length ?? 0;
  const busy = start.isPending || send.isPending || Boolean(runId && ["streaming", "settled"].includes(stream.status));

  const onDone = (completed: RunRecord, message?: string) => {
    if (ignoredRuns.current.delete(completed.runId)) return;
    detachRun(completed.runId);
    if (completed.status !== "succeeded") {
      setPending(null);
      setRunError(completed.error ?? "Career Lab run did not complete");
      return;
    }
    const result = completed.result as { sessionId?: string; needsSelection?: boolean; route?: { reason?: string } } | null;
    if (result?.needsSelection) {
      const reason = result.route?.reason ?? "Choose the Career Lab skill that best fits this request.";
      const userText = message ?? "";
      setPending(null);
      setSelectionNotice(reason);
      setSelectionExchange({ userText, assistantText: reason });
      setComposer(userText);
      setRetryMessage(userText);
    } else if (result?.sessionId) {
      setPending(null);
      setSelectionExchange(null);
      setSelectedSessionId(result.sessionId);
      setRetryMessage("");
      if (message) setComposer((value) => (value.trim() === message.trim() ? "" : value));
    }
  };

  const sendMessage = async (retry?: string, forceNewSession = false) => {
    const message = (retry ?? composer).trim();
    if (!message || busy) return;
    setRunError("");
    setSelectionNotice("");
    setSelectionExchange(null);
    setRetryMessage(message);
    setSuppressedRunId(null);
    stream.reset();
    setPending({ text: message, baseline: forceNewSession ? 0 : active?.turns?.length ?? 0 });
    try {
      const launched = active && !forceNewSession
        ? await send.mutateAsync({
            sessionId: active.sessionId,
            message,
            skill: skill ? (skill as import("./use-career-lab").CareerLabSkillName) : undefined,
            context,
            onDone: (completed) => onDone(completed, message),
          })
        : await start.mutateAsync({
            message,
            goal: message,
            skill: skill ? (skill as import("./use-career-lab").CareerLabSkillName) : undefined,
            context,
            onDone: (completed) => onDone(completed, message),
          });
      attachRun(launched.runId);
    } catch (error) {
      setPending(null);
      setRetryMessage(message);
      setRunError(error instanceof Error ? error.message : "Career Lab run failed");
    }
  };

  const stop = () => {
    if (!runId) return;
    ignoredRuns.current.add(runId);
    attachedRuns.current.delete(runId);
    completedBeforeAttach.current.delete(runId);
    setSuppressedRunId(runId);
    stream.stop();
    setStreamRunId(null);
    setPending(null);
  };

  const endSession = async () => {
    if (!active || active.status !== "active") return;
    try {
      const launched = await end.mutateAsync({
        sessionId: active.sessionId,
        onDone: (completed) => onDone(completed),
      });
      attachRun(launched.runId);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Could not end the session");
    }
  };

  const durableTurns = active?.turns?.length ?? 0;
  const durableAdvanced = durableTurns > baseline;
  const showThread = Boolean(active || pending || selectionExchange || runId);
  const canCompose = active?.status === "active" || (!active && (Boolean(pending) || Boolean(selectionExchange) || Boolean(runId)));
  const chatMessages: ChatThreadMessage[] = (active?.turns ?? []).map((turn, index) => ({
    id: `${turn.turnId}-${index}`,
    role: turn.role,
    parts: [
      { kind: "text" as const, text: turn.text },
      ...(turn.notice ? [{ kind: "notice" as const, message: turn.notice }] : []),
    ],
  }));
  if (pending && !durableAdvanced) {
    chatMessages.push({ id: "pending-user", role: "user", parts: [{ kind: "text", text: pending.text }] });
  }
  if (selectionExchange) {
    chatMessages.push(
      { id: "selection-user", role: "user", parts: [{ kind: "text", text: selectionExchange.userText }] },
      { id: "selection-assistant", role: "assistant", parts: [{ kind: "notice", message: selectionExchange.assistantText }] },
    );
  }

  const error = stream.error || runError;
  const historyItems: ChatSessionHistoryItem[] = useMemo(() => (sessions.data?.sessions ?? []).map((row) => ({
    id: row.sessionId,
    title: row.title || row.goal || "Untitled Career Lab",
    detail: `${row.status === "active" ? "Drafting now" : "Completed"} · ${row.turnCount} turns · ${new Date(row.startedAt).toLocaleDateString()}`,
    status: row.status,
    archived: Boolean(row.archivedAt),
  })), [sessions.data?.sessions]);

  return (
    <div className={cn("space-y-6", CHAT_PAGE_WIDTH)}>
      <GuidedWorkspaceHeader
        tone="career-lab"
        icon={<Sparkles />}
        eyebrow="Drafting studio"
        title="Career Lab"
        description="Work through a career question with one verified skill at a time. Every output stays a draft until you decide what to do next."
        meta={
          <>
            <Badge variant={active?.status === "active" ? "secondary" : "outline"}>{active ? (active.status === "active" ? "Session live" : "Session ended") : "Ready to explore"}</Badge>
            <Badge variant="outline">No external actions</Badge>
          </>
        }
        actions={active?.status === "active" ? (
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="outline"><SquareCheckBig aria-hidden="true" />End session</Button>} />
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>End this Career Lab session?</AlertDialogTitle>
                <AlertDialogDescription>The transcript stays available, and no synthetic recap will be added.</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep working</AlertDialogCancel>
                <AlertDialogAction disabled={end.isPending} onClick={() => void endSession()}>End session</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : undefined}
      />

      {error || selectionNotice ? (
        <Alert variant={error ? "destructive" : "default"} role="alert">
          <AlertTitle>{error ? "Career Lab needs attention" : "Choose a skill"}</AlertTitle>
          <AlertDescription>
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">{error || selectionNotice}</span>
              {error && retryMessage ? (
                <Button variant="outline" size="sm" onClick={() => void sendMessage(retryMessage, !active)} disabled={busy}>
                  Retry draft
                </Button>
              ) : null}
              {selectionNotice && retryMessage ? (
                <Button variant="outline" size="sm" onClick={() => void sendMessage(retryMessage, !active)} disabled={!skill || busy}>
                  Continue with skill
                </Button>
              ) : null}
              {selectionNotice && !active ? (
                <div className="w-full sm:max-w-sm">
                  <CareerLabSkillPicker skill={skill} setSkill={setSkill} skills={skills} selectRef={skillRef} id="career-skill-selection" />
                </div>
              ) : null}
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className={cn("grid items-start gap-6", active && "xl:grid-cols-[minmax(0,1fr)_22rem]")}>
        <main className="flex min-w-0 flex-col gap-4">
          <Card className="min-w-0 overflow-hidden rounded-2xl">
            <CardHeader className="border-b bg-muted/25 py-4">
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="size-5 text-primary" aria-hidden="true" />{active?.title || (showThread ? "Career Lab workspace" : "Start a Career Lab session")}</CardTitle>
              <CardDescription>{active ? active.goal || "A focused Career Lab session" : "Create a session when you are ready to work through a career question."}</CardDescription>
            </CardHeader>
            <CardContent className={cn("flex flex-col gap-4 p-4 sm:p-6", CHAT_SURFACE_HEIGHT)}>
              {sessionLoading ? <Skeleton className="h-full w-full" /> : null}
              {!sessionLoading && !showThread ? <WorkspaceEmptyState icon={MessageCircleMore} title="Turn a career question into a useful draft" description="Start with one focused request. After the session begins, you can add only the career context that should shape the next draft." actionLabel="Create Career Lab session" onAction={() => setNewOpen(true)} steps={[{ icon: MessageCircleMore, title: "Ask one focused question", description: "Start with the decision, draft, comparison, or next step you need." }, { icon: ListChecks, title: "Set context when needed", description: "Once the session starts, include a profile, job, resume version, or offer references." }, { icon: FileText, title: "Review the draft", description: "Keep every output as a draft until you decide how to use it." }]} /> : null}
              {showThread ? (
                <ChatThread
                  messages={chatMessages}
                  streaming={runId && !durableAdvanced ? stream.parts : null}
                  streamingActive={stream.status === "streaming"}
                  showReasoning={false}
                  assistantName="Career Lab draft"
                  assistantIcon={<Sparkles className="size-4" aria-hidden="true" />}
                  renderAfter={(message) => {
                    const turns = active?.turns ?? [];
                    const turn = turns.find((candidate) => `${candidate.turnId}-${turns.indexOf(candidate)}` === message.id);
                    if (!turn?.artifact) return null;
                    return <div className="ml-10 mt-2 rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm"><Badge variant="secondary">Draft</Badge><p className="mt-2 font-medium">{turn.artifact.title}</p><p className="mt-1 text-muted-foreground">{turn.artifact.summary}</p></div>;
                  }}
                />
              ) : null}
              {busy && runId && !stream.parts.length && !durableAdvanced && !selectionExchange ? (
                <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
                  <Spinner />
                  <span>Career Lab is thinking…</span>
                </div>
              ) : null}
            </CardContent>
            {canCompose ? <div className="border-t bg-card/95 p-4 sm:p-6">
              <ChatComposer
                value={composer}
                onChange={setComposer}
                onSend={() => void sendMessage()}
                onStop={stop}
                busy={busy}
                settling={stream.status === "settled"}
                ariaLabel="Message Career Lab"
                sendLabel="Send"
                placeholder="Ask for a draft, plan, comparison, or next step…"
              />
            </div> : active?.status === "ended" ? <div className="border-t bg-muted/20 p-4 text-center text-sm text-muted-foreground">This draft session has ended. Start a new session when you are ready to explore another question.</div> : null}
          </Card>
        </main>

        {active ? (
          <aside className="min-w-0 space-y-4 xl:sticky xl:top-4" aria-label="Career Lab controls">
            <CareerLabContextRail skill={skill} setSkill={setSkill} skills={skills} goal={active.goal} context={context} setContext={setContext} skillRef={skillRef} />
          </aside>
        ) : null}
      </div>

      <ChatSessionHistory
        ariaLabel="Career Lab sessions"
        items={historyItems}
        selectedId={displayedSessionId}
        onSelect={setSelectedSessionId}
        showArchived={showArchived}
        onShowArchivedChange={setShowArchived}
        isLoading={sessions.isPending}
        isError={sessions.isError}
        onRetry={() => void sessions.refetch()}
        emptyMessage="No saved Career Lab sessions yet. Start one when you are ready to draft."
        createLabel={activeSummary ? undefined : "New Career Lab session"}
        onCreate={activeSummary ? undefined : () => setNewOpen(true)}
        onRename={(sessionId, title) => void rename.mutateAsync({ sessionId, title })}
        onArchive={(sessionId) => archive.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedSessionId) setSelectedSessionId(null); } })}
        onUnarchive={(sessionId) => unarchive.mutate({ sessionId })}
        onDelete={(sessionId) => remove.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedSessionId) setSelectedSessionId(null); } })}
        renamePending={rename.isPending}
        deletePending={remove.isPending}
        deleteDescription="This permanently removes the saved transcript from this workspace."
      />

      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Career Lab session</DialogTitle>
            <DialogDescription>Ask for a draft, plan, comparison, or next step. Session setup and reference context become available once the session begins.</DialogDescription>
          </DialogHeader>
          <Textarea aria-label="Career Lab request" autoFocus rows={4} value={composer} onChange={(event) => setComposer(event.target.value)} placeholder="Help me compare these offers and draft a decision checklist…" />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setNewOpen(false)}>Cancel</Button>
            <Button disabled={!composer.trim() || busy} onClick={() => { setNewOpen(false); void sendMessage(undefined, true); }}><Sparkles aria-hidden="true" />Start session</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
