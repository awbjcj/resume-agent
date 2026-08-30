import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FileText, ListChecks, MessageCircleMore, Sparkles, SquareCheckBig } from "lucide-react";

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
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useChatStream } from "@/lib/chat/useChatStream";
import type { RunRecord } from "@/lib/runs/store";
import { cn } from "@/lib/utils";

import { CareerLabContextRail } from "./CareerLabContextRail";
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

// Hoisted out of render on purpose. `ChatMessage` is memoized behind a custom
// comparator that checks `assistantIcon` by reference; an element built inline
// in JSX is a new object every render, so passing one there fails that check and
// re-renders — and re-parses the markdown of — every message already in the
// thread on every stream delta.
const CAREER_LAB_ICON = <Sparkles className="size-4" aria-hidden="true" />;

export function CareerLabPage() {
  const [newOpen, setNewOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [searchParams] = useSearchParams();
  const sessions = useCareerLabSessions({ includeArchived: showArchived });
  const skills = useCareerLabSkills();
  // Active threads are per job, so there can be several. The API exposes the
  // complete active collection outside paginated history. `activeSummary` picks
  // which one to *show* — the un-anchored thread this page owns, else the most
  // recent — rather than whatever the directory scan listed first.
  // `unanchoredActive` is a separate question: whether this page may *start* one.
  // Gating creation on `activeSummary` conflated the two, so a single thread
  // opened from any job modal hid the New-session button (and the empty state
  // that also offers it), leaving no way to start an un-anchored thread the
  // backend would happily accept — `job_id=None` is its own bucket.
  const { activeSummary, unanchoredActive } = useMemo(() => {
    const active = (sessions.data?.activeSessions ?? sessions.data?.sessions ?? [])
      .filter((row) => row.status === "active")
      .sort((left, right) => right.startedAt.localeCompare(left.startedAt));
    const unanchored = active.find((row) => row.jobId == null);
    return { activeSummary: unanchored ?? active[0], unanchoredActive: unanchored };
  }, [sessions.data?.activeSessions, sessions.data?.sessions]);
  // `?session=` is an opening selection, not a standing one — a job's Career Lab
  // tab links here to name the thread to show. It seeds the selection instead of
  // acting as a fallback beneath it, because a fallback outlives the action meant
  // to clear it: deleting or archiving the linked thread resets
  // `selectedSessionId`, and a still-present param would immediately re-select
  // the row that no longer exists.
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    () => searchParams.get("session"),
  );
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
    const result = completed.result as { sessionId?: string } | null;
    if (result?.sessionId) {
      setPending(null);
      setSelectedSessionId(result.sessionId);
      setRetryMessage("");
      if (message) setComposer((value) => (value.trim() === message.trim() ? "" : value));
    } else {
      setPending(null);
      setRunError("Career Lab completed without returning a session.");
    }
  };

  const sendMessage = async (retry?: string, forceNewSession = false) => {
    const message = (retry ?? composer).trim();
    if (!message || busy) return;
    setRunError("");
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
  const showThread = Boolean(active || pending || runId);
  const canCompose = active?.status === "active" || (!active && (Boolean(pending) || Boolean(runId)));
  const chatTurns = active?.turns ?? [];
  const chatMessages: ChatThreadMessage[] = chatTurns.map((turn, index) => ({
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

  // Keyed exactly as `chatMessages` ids are built above. `renderAfter` used to
  // recover the turn with `find` + an inner `indexOf`, which is quadratic on its
  // own and runs once per rendered message — cubic in thread length, on every
  // stream delta. One map built per render makes each lookup O(1).
  const turnByMessageId = new Map<string, (typeof chatTurns)[number]>(
    chatTurns.map((turn, index) => [`${turn.turnId}-${index}`, turn]),
  );

  const error = stream.error || runError;
  const historyItems: ChatSessionHistoryItem[] = useMemo(() => (sessions.data?.sessions ?? []).map((row) => ({
    id: row.sessionId,
    // The anchored job leads the detail line: threads started from a job modal
    // often share a title, and without it several were indistinguishable here.
    detail: [
      [row.jobCompany, row.jobTitle].filter(Boolean).join(" · "),
      row.status === "active" ? "Drafting now" : "Completed",
      `${row.turnCount} turns`,
      new Date(row.startedAt).toLocaleDateString(),
    ].filter(Boolean).join(" · "),
    title: row.title || row.goal || "Untitled Career Lab",
    status: row.status,
    archived: Boolean(row.archivedAt),
  })), [sessions.data?.sessions]);

  return (
    <div className={cn("space-y-6", CHAT_PAGE_WIDTH)}>
      <GuidedWorkspaceHeader
        tone="career-lab"
        icon={<Sparkles />}
        eyebrow={active ? "Career Lab" : "Drafting studio"}
        title={active?.title || "Career Lab"}
        description={active?.goal || "Work through a career question with one verified skill at a time. Every output stays a draft until you decide what to do next."}
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

      {error ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Career Lab needs attention</AlertTitle>
          <AlertDescription>
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">{error}</span>
              {error && retryMessage ? (
                <Button variant="outline" size="sm" onClick={() => void sendMessage(retryMessage, !active)} disabled={busy}>
                  Retry draft
                </Button>
              ) : null}
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className={cn("grid items-start gap-6", active && "xl:grid-cols-[minmax(0,1fr)_22rem]")}>
        <main className="flex min-w-0 flex-col gap-4">
          <Card className="min-w-0 overflow-hidden rounded-2xl">
            <CardContent className={cn("flex flex-col gap-4", showThread ? "p-4 sm:p-6" : "p-0", CHAT_SURFACE_HEIGHT)}>
              {sessionLoading ? <Skeleton className="h-full w-full" /> : null}
              {!sessionLoading && !showThread ? <WorkspaceEmptyState icon={MessageCircleMore} title="Turn a career question into a useful draft" description="Start with one focused request. After the session begins, you can add only the career context that should shape the next draft." actionLabel="Create Career Lab session" onAction={() => setNewOpen(true)} steps={[{ icon: MessageCircleMore, title: "Ask one focused question", description: "Start with the decision, draft, comparison, or next step you need." }, { icon: ListChecks, title: "Set context when needed", description: "Once the session starts, include a profile, job, resume version, or offer references." }, { icon: FileText, title: "Review the draft", description: "Keep every output as a draft until you decide how to use it." }]} /> : null}
              {showThread ? (
                <ChatThread
                  messages={chatMessages}
                  streaming={runId && !durableAdvanced ? stream.parts : null}
                  streamingActive={stream.status === "streaming"}
                  showReasoning={false}
                  assistantName="Career Lab draft"
                  assistantIcon={CAREER_LAB_ICON}
                  renderAfter={(message) => {
                    const turn = turnByMessageId.get(message.id);
                    if (!turn?.artifact) return null;
                    return <div className="ml-10 mt-2 rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm"><Badge variant="secondary">Draft</Badge><p className="mt-2 font-medium">{turn.artifact.title}</p><p className="mt-1 text-muted-foreground">{turn.artifact.summary}</p></div>;
                  }}
                />
              ) : null}
              {busy && runId && !stream.parts.length && !durableAdvanced ? (
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
        createLabel={unanchoredActive ? undefined : "New Career Lab session"}
        onCreate={unanchoredActive ? undefined : () => setNewOpen(true)}
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
