import { useRef, useState } from "react";
import { Bot, Clock3, FileCheck2, MessageCircleQuestion, SearchCheck, Sparkles, SquareCheckBig } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

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
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useChatStream } from "@/lib/chat/useChatStream";
import { cn } from "@/lib/utils";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";

import { AgendaRail } from "./AgendaRail";
import { DraftNoteCard } from "./DraftNoteCard";
import { ImpactCard } from "./ImpactCard";
import { ResearchActionCard } from "./ResearchActionCard";
import {
  useCoachSession,
  useCoachSessions,
  useArchiveCoachSession,
  useDeleteCoachSession,
  useDiscardCoachNote,
  useEndCoachSession,
  useRenameCoachSession,
  useSaveCoachNote,
  useSendCoachMessage,
  useStartCoachSession,
  useUnarchiveCoachSession,
} from "./use-coach";

// Hoisted out of render on purpose. `ChatMessage` is memoized behind a custom
// comparator that checks `assistantIcon` by reference; an element built inline
// in JSX is a new object every render, so passing one there fails that check and
// re-renders — and re-parses the markdown of — every message already in the
// thread on every stream delta.
const COACH_ICON = <Sparkles className="size-4" aria-hidden="true" />;

function RunError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>The coach could not finish that step</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center gap-3">
        <span className="flex-1">{message}</span>
        <Button size="sm" variant="outline" onClick={onRetry}>Retry</Button>
      </AlertDescription>
    </Alert>
  );
}

export function CoachPage() {
  const [showArchived, setShowArchived] = useState(false);
  const sessions = useCoachSessions(showArchived);
  const activeSummary = sessions.data?.sessions?.find((session) => session.status === "active");
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const displayedSessionId = currentSessionId ?? activeSummary?.sessionId ?? null;
  const session = useCoachSession(displayedSessionId);
  const start = useStartCoachSession();
  const send = useSendCoachMessage();
  const end = useEndCoachSession();
  const saveNote = useSaveCoachNote();
  const discardNote = useDiscardCoachNote();
  const archive = useArchiveCoachSession();
  const unarchive = useUnarchiveCoachSession();
  const remove = useDeleteCoachSession();
  const rename = useRenameCoachSession();
  const [composer, setComposer] = useState("");
  const [lastMessage, setLastMessage] = useState("");
  // The turn only reaches the durable transcript when the run finishes, so
  // without a local echo the user's own message is invisible for the whole
  // reply. `baseline` is the turn count at launch: the echo retires the
  // moment the persisted thread passes it, which also stops it
  // double-rendering after the refetch.
  const [pending, setPending] = useState<{ text: string; baseline: number } | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "error">("idle");
  const [runError, setRunError] = useState("");
  const [streamRunId, setStreamRunId] = useState<string | null>(null);
  const [streamBaseline, setStreamBaseline] = useState(0);
  const [suppressedRunId, setSuppressedRunId] = useState<string | null>(null);
  const ignoredRuns = useRef(new Set<string>());
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [build, setBuild] = useState(true);
  const recoveredRunId = useRunStore((state) => {
    const run = Object.values(state.runs).find(
      (candidate) =>
        ["profile-coach-turn", "profile-coach-end"].includes(candidate.kind) &&
        ["queued", "running", "cancelling"].includes(candidate.status) &&
        candidate.meta?.sessionId === displayedSessionId,
    );
    return run?.runId ?? null;
  });
  const recoveredBaseline = useRunStore((state) => {
    const run = Object.values(state.runs).find(
      (candidate) =>
        ["profile-coach-turn", "profile-coach-end"].includes(candidate.kind) &&
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

  const startSession = async () => {
    if (starting || start.isPending) return;
    setStarting(true);
    setRunError("");
    setStreamBaseline(0);
    setSuppressedRunId(null);
    stream.reset();
    try {
      const launched = await start.mutateAsync({
        onDone: (completed: RunRecord) => {
          if (ignoredRuns.current.delete(completed.runId)) return;
          setStarting(false);
          if (completed.status === "succeeded") {
            const result = completed.result as { sessionId?: string } | null;
            if (result?.sessionId) setCurrentSessionId(result.sessionId);
          } else {
            setRunError(completed.error ?? "Session setup failed");
          }
        },
      });
      setStreamRunId(launched.runId);
    } catch (error) {
      setStarting(false);
      setRunError(error instanceof Error ? error.message : "Session setup failed");
    }
  };

  const sendMessage = async (message = composer.trim()) => {
    if (!session.data || !message || runState === "running") return;
    setLastMessage(message);
    setRunState("running");
    setRunError("");
    setStreamBaseline(session.data.turns?.length ?? 0);
    setSuppressedRunId(null);
    stream.reset();
    setPending({ text: message, baseline: session.data.turns?.length ?? 0 });
    try {
      const launched = await send.mutateAsync({
        sessionId: session.data.sessionId,
        message,
        onDone: (completed: RunRecord) => {
          if (ignoredRuns.current.delete(completed.runId)) return;
          setPending(null);
          if (completed.status === "succeeded") {
            setComposer((current) => current.trim() === message ? "" : current);
            setRunState("idle");
          } else {
            setRunState("error");
            setRunError(completed.error ?? "Message failed");
          }
        },
      });
      setStreamRunId(launched.runId);
    } catch (error) {
      setPending(null);
      setRunState("error");
      setRunError(error instanceof Error ? error.message : "Message failed");
    }
  };

  const stopMessage = () => {
    if (attachedRunId) ignoredRuns.current.add(attachedRunId);
    setSuppressedRunId(attachedRunId);
    stream.stop();
    setStreamRunId(null);
    setStarting(false);
    setEnding(false);
    setRunState("idle");
    setRunError("");
    setPending(null);
  };

  const endSession = async () => {
    if (!session.data) return;
    setEnding(true);
    setStreamBaseline(session.data.turns?.length ?? 0);
    setSuppressedRunId(null);
    stream.reset();
    try {
      const launched = await end.mutateAsync({
        sessionId: session.data.sessionId,
        build,
        onDone: (completed: RunRecord) => {
          if (ignoredRuns.current.delete(completed.runId)) return;
          setEnding(false);
          if (completed.status === "succeeded") {
            const result = completed.result as { session?: { sessionId?: string } } | null;
            if (result?.session?.sessionId) setCurrentSessionId(result.session.sessionId);
          } else {
            setRunError(completed.error ?? "Could not end session");
          }
        },
      });
      setStreamRunId(launched.runId);
    } catch (error) {
      setEnding(false);
      setRunError(error instanceof Error ? error.message : "Could not end session");
    }
  };

  if (sessions.isLoading || (displayedSessionId && session.isLoading)) {
    return <div className="space-y-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[32rem] w-full" /></div>;
  }

  if (sessions.isError || (displayedSessionId && session.isError)) {
    return <RunError message="Profile coach data could not be loaded." onRetry={() => { void sessions.refetch(); void session.refetch(); }} />;
  }

  const active = session.data;
  const pendingDrafts = active?.draftNotes?.filter((note) => note.status === "pending") ?? [];
  const savedDrafts = active?.draftNotes?.filter((note) => note.status === "saved") ?? [];
  const historyItems: ChatSessionHistoryItem[] = (sessions.data?.sessions ?? []).map((row) => {
    const date = new Date(row.startedAt).toLocaleDateString();
    return {
      id: row.sessionId,
      title: row.sessionTitle || `Coaching · ${date}`,
      detail: `${row.status === "active" ? "Coaching now" : "Completed"} · ${row.topicCount} topics · ${row.savedNoteCount} saved notes · ${date}`,
      status: row.status === "active" ? "active" : "ended",
      archived: Boolean(row.archivedAt),
    };
  });
  const durableTurns = active?.turns?.length ?? 0;
  const chatMessages: ChatThreadMessage[] = (() => {
    const durable = (active?.turns ?? []).map((turn, index) => {
      const notice = (turn as typeof turn & { notice?: string }).notice;
      const role: "assistant" | "user" = turn.role === "coach" ? "assistant" : "user";
      return {
        id: `${turn.at}-${index}`,
        role,
        parts: [
          { kind: "text" as const, text: turn.text },
          ...(notice ? [{ kind: "notice" as const, message: notice }] : []),
        ],
      };
    });
    if (!pending || durableTurns > pending.baseline) return durable;
    return [...durable, { id: "pending-user", role: "user" as const, parts: [{ kind: "text" as const, text: pending.text }] }];
  })();
  // `renderAfter` runs once per rendered message, so recovering a message's turn
  // with `indexOf` made the pass quadratic in thread length. One index map keeps
  // each lookup O(1); ids are unique by construction (`${turn.at}-${index}`).
  const turnIndexById = new Map(chatMessages.map((message, index) => [message.id, index]));
  const durableAdvanced = durableTurns > attachedBaseline;
  const streamingParts = attachedRunId && !durableAdvanced ? stream.parts : null;
  const busy = send.isPending || runState === "running" || stream.status === "streaming";
  const visibleError = stream.error || runError;
  const latestQuestion = [...(active?.turns ?? [])].reverse().find(
    (turn) => turn.role === "coach" && turn.kind === "question",
  );
  const currentQuestion = active?.topics?.some(
    (topic) => topic.id === latestQuestion?.topicId && topic.status === "open",
  )
    ? latestQuestion
    : undefined;

  return (
    <div className={cn("flex flex-col gap-8", CHAT_PAGE_WIDTH)}>
      <GuidedWorkspaceHeader
        tone="coach"
        icon={<Sparkles />}
        eyebrow="Guided evidence discovery"
        title="Profile coach"
        description="Turn overlooked outcomes, scope, and project evidence into grounded profile notes."
        meta={<>
          <Badge variant={active?.status === "active" ? "secondary" : "outline"}>{active?.status === "active" ? "Session live" : active?.status === "ended" ? "Session complete" : "Ready when you are"}</Badge>
          {active ? <Badge variant="outline">{active.topics?.length ?? 0} topics</Badge> : null}
          {active ? <Badge variant="outline">{pendingDrafts.length} awaiting approval</Badge> : null}
          {active ? <Badge variant="outline">{savedDrafts.length} saved</Badge> : null}
        </>}
        actions={<>{active?.status === "active" ? (
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="outline"><SquareCheckBig aria-hidden="true" />End session</Button>} />
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Finish this coaching session?</AlertDialogTitle>
                <AlertDialogDescription>{pendingDrafts.length ? `${pendingDrafts.length} pending draft note${pendingDrafts.length === 1 ? "" : "s"} will remain unsaved.` : "The coach will prepare a recap and close the thread."}</AlertDialogDescription>
              </AlertDialogHeader>
              <label className="flex items-center gap-3 rounded-lg border p-3 text-sm">
                <Checkbox checked={build} onCheckedChange={(checked) => setBuild(checked === true)} />
                Rebuild the profile and calculate impact
              </label>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep coaching</AlertDialogCancel>
                <AlertDialogAction disabled={ending} onClick={() => void endSession()}>{ending ? <Spinner data-icon="inline-start" /> : null}End session</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : active?.status === "ended" ? (
          <Button disabled={starting || start.isPending} onClick={() => void startSession()}>
            {starting || start.isPending ? <Spinner data-icon="inline-start" /> : <Sparkles aria-hidden="true" />}
            Start another session
          </Button>
        ) : null}</>}
      />

      {runError && runState !== "error" ? <Alert variant="destructive"><AlertTitle>Profile coach error</AlertTitle><AlertDescription>{runError}</AlertDescription></Alert> : null}

      {!active ? (
        <Card className="min-w-0 overflow-hidden rounded-2xl">
          <CardHeader className="border-b bg-muted/20">
            <div className="flex items-center gap-2">
              <Bot className="size-5 text-primary" aria-hidden="true" />
              <CardTitle>Profile coach workspace</CardTitle>
            </div>
            <CardDescription>Create a session when you are ready to turn overlooked experience into grounded profile evidence.</CardDescription>
          </CardHeader>
          <CardContent className={cn("flex flex-col gap-4 p-4 sm:p-6", CHAT_SURFACE_HEIGHT)}>
            {starting && attachedRunId ? (
              <>
                <ChatThread
                  messages={[]}
                  streaming={stream.parts}
                  streamingActive={stream.status === "streaming"}
                  assistantName="Profile coach"
                  assistantIcon={COACH_ICON}
                />
                {!stream.parts.length ? (
                  <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Spinner /> Preparing your first coaching question…
                  </div>
                ) : null}
                <Button className="self-center" variant="outline" onClick={stopMessage}>
                  Stop generating
                </Button>
              </>
            ) : (
              <WorkspaceEmptyState
                icon={Sparkles}
                title="Find the evidence your profile is missing"
                description="The coach reviews your current facts, asks one focused question at a time, and drafts only claims grounded in your answers."
                actionLabel="Start coaching session"
                actionIcon={starting || start.isPending ? <Spinner data-icon="inline-start" /> : <Sparkles aria-hidden="true" />}
                busy={starting || start.isPending}
                onAction={() => void startSession()}
                steps={[
                  { icon: SearchCheck, title: "Review gaps", description: "Start with evidence your current profile does not yet show." },
                  { icon: MessageCircleQuestion, title: "Answer one question", description: "Stay focused while the coach follows the strongest thread." },
                  { icon: FileCheck2, title: "Approve grounded notes", description: "Review every claim and its supporting words before saving." },
                ]}
              />
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <Card className="min-w-0 overflow-hidden rounded-2xl">
            <CardHeader className="border-b bg-muted/20 py-4">
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="size-5 text-primary" aria-hidden="true" />{active.sessionTitle || "Coaching thread"}</CardTitle>
              <CardDescription className="flex items-center gap-2 text-sm"><Clock3 className="size-4" aria-hidden="true" />Started {new Date(active.startedAt).toLocaleString()}</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className={cn("flex flex-col gap-4 p-4 sm:p-6", CHAT_SURFACE_HEIGHT)}>
                <ChatThread
                  messages={chatMessages}
                  streaming={streamingParts}
                  streamingActive={stream.status === "streaming"}
                  assistantName="Profile coach"
                  assistantIcon={COACH_ICON}
                  renderAfter={(message) => {
                    const index = turnIndexById.get(message.id) ?? -1;
                    const turn = active.turns?.[index];
                    if (!turn?.researchActions?.length) return null;
                    return (
                      <div className="mt-3 space-y-2">
                        {turn.researchActions.map((action, actionIndex) => (
                          <ResearchActionCard
                            key={`${action.kind}-${action.target}-${actionIndex}`}
                            action={action}
                          />
                        ))}
                      </div>
                    );
                  }}
                />
                {busy && !stream.parts.length ? (
                  <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <Spinner />
                    <span>The coach is reviewing your evidence…</span>
                  </div>
                ) : null}
                {(stream.status === "error" || runState === "error") && visibleError ? (
                  <RunError
                    message={visibleError}
                    onRetry={() => {
                      stream.reset();
                      void sendMessage(lastMessage);
                    }}
                  />
                ) : null}
                <div className="space-y-4">
                  {(active.draftNotes ?? []).map((note) => (
                    <DraftNoteCard
                      key={`${note.topicId}-${note.status}`}
                      note={note}
                      saving={saveNote.isPending}
                      discarding={discardNote.isPending}
                      onSave={(draft) => void saveNote.mutateAsync({ sessionId: active.sessionId, topicId: draft.topicId, title: draft.title, summary: draft.summary, quotes: draft.quotes ?? [] })}
                      onDiscard={() => void discardNote.mutateAsync({ sessionId: active.sessionId, topicId: note.topicId })}
                    />
                  ))}
                  {active.recap ? <Card className="bg-muted/30"><CardHeader><CardTitle className="text-lg">Session recap</CardTitle></CardHeader><CardContent className="text-base leading-7"><ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{active.recap}</ReactMarkdown></CardContent></Card> : null}
                  {active.impact ? <ImpactCard impact={active.impact} /> : null}
                </div>
              </div>
              {active.status === "active" ? (
                <div className="border-t bg-card p-5 sm:p-6">
                  <ChatComposer
                    value={composer}
                    onChange={setComposer}
                    onSend={() => void sendMessage()}
                    onStop={stopMessage}
                    busy={busy}
                    settling={stream.status === "settled"}
                    ariaLabel="Message your profile coach"
                    placeholder="Share the situation, what you did, and what changed…"
                  />
                </div>
              ) : null}
            </CardContent>
          </Card>
          <aside className="min-w-0 xl:sticky xl:top-4">
            <AgendaRail
              topics={active.topics ?? []}
              currentTopicId={currentQuestion?.topicId}
              currentQuestion={currentQuestion?.text}
            />
          </aside>
        </div>
      )}

      <ChatSessionHistory
        ariaLabel="Profile coach sessions"
        items={historyItems}
        selectedId={displayedSessionId}
        onSelect={setCurrentSessionId}
        showArchived={showArchived}
        onShowArchivedChange={setShowArchived}
        isLoading={sessions.isPending}
        isError={sessions.isError}
        onRetry={() => void sessions.refetch()}
        emptyMessage="No coaching sessions yet. Start one when you are ready to uncover stronger evidence."
        createLabel="New coaching session"
        createDisabled={starting || start.isPending}
        onCreate={() => void startSession()}
        onRename={(sessionId, title) => rename.mutate({ sessionId, title })}
        onArchive={(sessionId) => archive.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedSessionId) setCurrentSessionId(null); } })}
        onUnarchive={(sessionId) => unarchive.mutate({ sessionId })}
        onDelete={(sessionId) => remove.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedSessionId) setCurrentSessionId(null); } })}
        renamePending={rename.isPending}
        deletePending={remove.isPending}
        deleteDescription="The conversation transcript and recap will be permanently removed. Saved notes are kept in your profile."
      />
    </div>
  );
}
