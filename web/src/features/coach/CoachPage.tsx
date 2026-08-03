import { useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, ChevronDown, Clock3, EllipsisVertical, FileCheck2, History, MessageCircleQuestion, Pencil, SearchCheck, Sparkles, SquareCheckBig, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
import { GuidedWorkspaceHeader } from "@/components/chat/GuidedWorkspaceHeader";
import { CHAT_PAGE_WIDTH, CHAT_SURFACE_HEIGHT } from "@/components/chat/layout";
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
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
  type CoachSessionSummary,
} from "./use-coach";

function CoachSessionActions({ row, current = false, onArchived, onDelete, onRename }: { row: CoachSessionSummary; current?: boolean; onArchived?: () => void; onDelete: (row: CoachSessionSummary) => void; onRename: (row: CoachSessionSummary) => void }) {
  const archive = useArchiveCoachSession();
  const unarchive = useUnarchiveCoachSession();
  return <DropdownMenu><DropdownMenuTrigger render={<Button size="icon" variant="ghost" aria-label={current ? "Actions for current coaching session" : `Actions for coaching session ${row.sessionId}`}><EllipsisVertical /></Button>} /><DropdownMenuContent align="end"><DropdownMenuGroup>
    <DropdownMenuItem onClick={() => onRename(row)}><Pencil />Rename</DropdownMenuItem>
    {row.status === "ended" && !row.archivedAt ? <DropdownMenuItem onClick={() => { const input = { sessionId: row.sessionId }; if (onArchived) archive.mutate(input, { onSuccess: onArchived }); else archive.mutate(input); }}><Archive />Archive</DropdownMenuItem> : null}
    {row.archivedAt ? <DropdownMenuItem onClick={() => unarchive.mutate({ sessionId: row.sessionId })}><ArchiveRestore />Unarchive</DropdownMenuItem> : null}
    <DropdownMenuItem variant="destructive" onClick={() => onDelete(row)}><Trash2 />Delete</DropdownMenuItem>
  </DropdownMenuGroup></DropdownMenuContent></DropdownMenu>;
}

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

function PastSession({ sessionId }: { sessionId: string }) {
  const session = useCoachSession(sessionId);
  if (session.isLoading) return <Skeleton className="h-24 w-full" />;
  if (session.isError) return <div className="flex items-center justify-between gap-3 pt-3 text-sm text-muted-foreground"><span>Could not load session details.</span><Button size="sm" variant="outline" onClick={() => void session.refetch()}>Try again</Button></div>;
  if (!session.data) return <p className="text-sm text-muted-foreground">Session details unavailable.</p>;
  return (
    <div className="space-y-4 pt-3">
      {(session.data.turns ?? []).map((turn, index) => (
        <div key={`${turn.at}-${index}`} className="text-sm">
          <span className="font-medium">{turn.role === "coach" ? "Coach" : "You"}: </span>
          <span className="text-muted-foreground">{turn.text}</span>
        </div>
      ))}
      {session.data.recap ? <p className="rounded-lg bg-muted/50 p-3 text-sm">{session.data.recap}</p> : null}
      {session.data.impact ? <ImpactCard impact={session.data.impact} /> : null}
    </div>
  );
}

export function CoachPage() {
  const [showArchived, setShowArchived] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CoachSessionSummary | null>(null);
  const [pendingRename, setPendingRename] = useState<CoachSessionSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const sessions = useCoachSessions(showArchived);
  const activeSummary = sessions.data?.sessions?.find((session) => session.status === "active");
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const displayedSessionId = activeSummary?.sessionId ?? currentSessionId;
  const session = useCoachSession(displayedSessionId);
  const start = useStartCoachSession();
  const send = useSendCoachMessage();
  const end = useEndCoachSession();
  const saveNote = useSaveCoachNote();
  const discardNote = useDiscardCoachNote();
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

  const pastSessions = useMemo(
    () =>
      (sessions.data?.sessions ?? []).filter(
        (candidate) => candidate.status !== "active" && candidate.sessionId !== displayedSessionId,
      ),
    [displayedSessionId, sessions.data?.sessions],
  );

  const startSession = async () => {
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
    } catch {
      setStarting(false);
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
    } catch {
      setEnding(false);
    }
  };

  if (sessions.isLoading || (activeSummary && session.isLoading)) {
    return <div className="space-y-4"><Skeleton className="h-16 w-full" /><Skeleton className="h-[32rem] w-full" /></div>;
  }

  if (sessions.isError || (activeSummary && session.isError)) {
    return <RunError message="Profile coach data could not be loaded." onRetry={() => { void sessions.refetch(); void session.refetch(); }} />;
  }

  const active = session.data;
  const pendingDrafts = active?.draftNotes?.filter((note) => note.status === "pending") ?? [];
  const savedDrafts = active?.draftNotes?.filter((note) => note.status === "saved") ?? [];
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
  const durableAdvanced = durableTurns > attachedBaseline;
  const streamingParts = attachedRunId && !durableAdvanced ? stream.parts : null;
  const busy = send.isPending || runState === "running" || stream.status === "streaming";
  const visibleError = stream.error || runError;

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
        ) : null}{active ? <CoachSessionActions current row={{ sessionId: active.sessionId, sessionTitle: active.sessionTitle, status: active.status, startedAt: active.startedAt, endedAt: active.endedAt, topicCount: active.topics?.length ?? 0, savedNoteCount: savedDrafts.length, archivedAt: active.archivedAt }} onArchived={() => setCurrentSessionId(null)} onDelete={setPendingDelete} onRename={(row) => { setPendingRename(row); setRenameTitle(row.sessionTitle || `Coaching · ${new Date(row.startedAt).toLocaleDateString()}`); }} /> : null}</>}
      />

      {runError && runState !== "error" ? <Alert variant="destructive"><AlertTitle>Profile coach error</AlertTitle><AlertDescription>{runError}</AlertDescription></Alert> : null}

      {!active ? (
        <Card className="min-h-[34rem] border-dashed bg-gradient-to-br from-card via-card to-primary/[0.05]">
          <CardContent className="flex min-h-[34rem] items-center justify-center py-14">
            {starting && attachedRunId ? (
              <div className="flex h-[28rem] w-full max-w-3xl flex-col gap-4">
                <ChatThread messages={[]} streaming={stream.parts} streamingActive={stream.status === "streaming"} />
                {!stream.parts.length ? (
                  <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Spinner /> Preparing your first coaching question…
                  </div>
                ) : null}
                <Button className="self-center" variant="outline" onClick={stopMessage}>
                  Stop generating
                </Button>
              </div>
            ) : (
              <Empty className="gap-7">
              <EmptyHeader>
                <EmptyMedia variant="icon"><Bot aria-hidden="true" /></EmptyMedia>
                <EmptyTitle>Find the evidence your profile is missing</EmptyTitle>
                <EmptyDescription>The coach reviews your current facts, asks one focused question at a time, and drafts only claims grounded in your answers.</EmptyDescription>
              </EmptyHeader>
              <EmptyContent className="max-w-3xl">
                <div className="grid w-full gap-3 text-left sm:grid-cols-3">
                  {[{ icon: SearchCheck, title: "Review gaps", copy: "Start with evidence your current profile does not yet show." }, { icon: MessageCircleQuestion, title: "Answer one question", copy: "Stay focused while the coach follows the strongest thread." }, { icon: FileCheck2, title: "Approve grounded notes", copy: "Review every claim and its supporting words before saving." }].map((step, index) => {
                    const StepIcon = step.icon;
                    return <div key={step.title} className="rounded-xl border bg-background/70 p-4">
                      <div className="flex items-center gap-2 text-sm font-semibold"><span className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary"><StepIcon className="size-4" aria-hidden="true" /></span><span className="text-xs text-muted-foreground">0{index + 1}</span></div>
                      <p className="mt-3 text-sm font-semibold">{step.title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.copy}</p>
                    </div>;
                  })}
                </div>
                <Button disabled={starting || start.isPending} onClick={() => void startSession()}>{starting || start.isPending ? <Spinner data-icon="inline-start" /> : <Sparkles aria-hidden="true" />}Start coaching session</Button>
              </EmptyContent>
              </Empty>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <Card className="min-w-0 overflow-hidden">
            <CardHeader className="border-b bg-muted/20">
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="size-5 text-primary" aria-hidden="true" />{active.sessionTitle || "Coaching thread"}</CardTitle>
              <CardDescription className="flex items-center gap-2 text-sm"><Clock3 className="size-4" aria-hidden="true" />Started {new Date(active.startedAt).toLocaleString()}</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className={cn("flex flex-col gap-4 p-5 sm:p-8", CHAT_SURFACE_HEIGHT)}>
                <ChatThread
                  messages={chatMessages}
                  streaming={streamingParts}
                  streamingActive={stream.status === "streaming"}
                  assistantName="Profile coach"
                  assistantIcon={<Sparkles className="size-4" aria-hidden="true" />}
                  renderAfter={(message) => {
                    const index = chatMessages.indexOf(message);
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
          <aside className="space-y-4 lg:sticky lg:top-4">
            <div className="xl:hidden">
              <Collapsible>
                <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-lg border bg-card px-4 py-3 text-sm font-medium">View evidence path<ChevronDown className="size-4 transition-transform duration-[160ms] ease-out-strong group-data-panel-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" /></CollapsibleTrigger>
                <CollapsibleContent className="translate-y-0 overflow-hidden pt-3 opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity"><AgendaRail topics={active.topics ?? []} /></CollapsibleContent>
              </Collapsible>
            </div>
            <div className="hidden xl:block"><AgendaRail topics={active.topics ?? []} /></div>
          </aside>
        </div>
      )}

      <section className="flex flex-col gap-3">
        {pastSessions.length ? <>
          <div className="flex items-center gap-2"><History className="size-4 text-muted-foreground" aria-hidden="true" /><h2 className="text-base font-semibold">Past sessions</h2><Badge variant="secondary">{pastSessions.length}</Badge></div>
          {pastSessions.map((past) => (
            <Collapsible key={past.sessionId} className="rounded-xl border bg-card px-4">
              <div className="flex items-center gap-2"><CollapsibleTrigger className="group/past flex min-w-0 flex-1 items-center justify-between gap-4 py-4 text-left"><span><span className="block text-sm font-medium">{past.sessionTitle || new Date(past.startedAt).toLocaleDateString()}</span><span className="text-xs text-muted-foreground">{past.topicCount} topics · {past.savedNoteCount} saved notes</span></span><span className="flex items-center gap-2">{past.archivedAt ? <Badge variant="outline">Archived</Badge> : null}<ChevronDown className="size-4 text-muted-foreground transition-transform duration-[160ms] ease-out-strong group-data-panel-open/past:rotate-180 motion-reduce:transition-none" aria-hidden="true" /></span></CollapsibleTrigger><CoachSessionActions row={past} onDelete={setPendingDelete} onRename={(row) => { setPendingRename(row); setRenameTitle(row.sessionTitle || `Coaching · ${new Date(row.startedAt).toLocaleDateString()}`); }} /></div>
              <CollapsibleContent className="translate-y-0 overflow-hidden border-t pb-4 opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity"><PastSession sessionId={past.sessionId} /></CollapsibleContent>
            </Collapsible>
          ))}
        </> : <p className="text-sm text-muted-foreground">No past coaching sessions.</p>}
        <Field orientation="horizontal"><Switch id="show-archived-coach" checked={showArchived} onCheckedChange={setShowArchived} /><FieldLabel htmlFor="show-archived-coach">Show archived</FieldLabel></Field>
      </section>

      <Dialog open={pendingRename != null} onOpenChange={(open) => { if (!open) setPendingRename(null); }}><DialogContent><DialogHeader><DialogTitle>Rename coaching session</DialogTitle><DialogDescription>Use a short title that will be easy to recognize in your history.</DialogDescription></DialogHeader><Input aria-label="Session title" autoFocus maxLength={120} value={renameTitle} onChange={(event) => setRenameTitle(event.target.value)} /><DialogFooter><Button variant="ghost" onClick={() => setPendingRename(null)}>Cancel</Button><Button disabled={!renameTitle.trim() || rename.isPending} onClick={() => { if (!pendingRename) return; rename.mutate({ sessionId: pendingRename.sessionId, title: renameTitle.trim() }, { onSuccess: () => setPendingRename(null) }); }}>Save title</Button></DialogFooter></DialogContent></Dialog>

      <AlertDialog open={pendingDelete != null} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Delete this coaching session?</AlertDialogTitle><AlertDialogDescription>The conversation transcript and recap will be permanently removed. Saved notes are kept in your profile.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Keep it</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={() => { if (!pendingDelete) return; const deletingDisplayed = pendingDelete.sessionId === displayedSessionId; remove.mutate({ sessionId: pendingDelete.sessionId }, { onSuccess: () => { if (deletingDisplayed) setCurrentSessionId(null); } }); setPendingDelete(null); }}>Delete</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </div>
  );
}
