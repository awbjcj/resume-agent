import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import {
  Archive,
  ArchiveRestore,
  Bot,
  MessageCircleMore,
  PanelRight,
  Sparkles,
  SquareCheckBig,
  Trash2,
} from "lucide-react";

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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useChatStream } from "@/lib/chat/useChatStream";
import type { RunRecord } from "@/lib/runs/store";
import { cn } from "@/lib/utils";

import {
  useArchiveCareerLabSession,
  useCareerLabRecoveredRun,
  useCareerLabSession,
  useCareerLabSessions,
  useCareerLabSkills,
  useDeleteCareerLabSession,
  useEndCareerLab,
  useSendCareerLabMessage,
  useStartCareerLab,
  useUnarchiveCareerLabSession,
  type CareerLabContext,
} from "./use-career-lab";

function ContextRail({
  skill,
  setSkill,
  skills,
  goal,
  setGoal,
  context,
  setContext,
  skillRef,
}: {
  skill: string;
  setSkill: (value: string) => void;
  skills: ReturnType<typeof useCareerLabSkills>;
  goal: string;
  setGoal: (value: string) => void;
  context: CareerLabContext;
  setContext: (value: CareerLabContext) => void;
  skillRef: RefObject<HTMLSelectElement | null>;
}) {
  const rows = skills.data?.skills ?? [];
  const updateId = (key: "jobId" | "resumeVersionId", value: string) => {
    const numeric = value ? Number(value) : undefined;
    setContext({ ...context, [key]: numeric });
  };
  const updateOfferIds = (value: string) => {
    const offerApplicationIds = value
      .split(",")
      .map((part) => Number(part.trim()))
      .filter((value) => Number.isInteger(value) && value > 0)
      .slice(0, 10);
    setContext({ ...context, offerApplicationIds });
  };
  return (
    <Card className="bg-card/90">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <PanelRight className="size-4 text-primary" aria-hidden="true" />
          Context &amp; skill
        </CardTitle>
        <CardDescription>Typed references guide the draft; nothing is changed.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="career-skill">Career skill</Label>
          <select
            id="career-skill"
            aria-label="Career skill"
            ref={skillRef}
            value={skill}
            onChange={(event) => setSkill(event.target.value)}
            className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">Let Career Lab route it</option>
            {rows.map((row) => (
              <option key={row.name} value={row.name} disabled={!row.isAvailable}>
                {row.name}{row.isAvailable ? "" : " — unavailable"}
              </option>
            ))}
          </select>
          {!skill && rows.length > 0 ? (
            <p className="text-xs text-muted-foreground">Ambiguous requests will ask you to choose.</p>
          ) : null}
          {rows.some((row) => row.name === skill && !row.isAvailable) ? (
            <p className="text-xs text-destructive">
              {rows.find((row) => row.name === skill)?.unavailableReason ?? "This skill is unavailable."}
            </p>
          ) : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="career-goal">Session goal</Label>
          <Textarea
            id="career-goal"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="What would a useful draft help you decide?"
            maxLength={2_000}
            rows={3}
            className="resize-none"
          />
        </div>
        <label className="flex items-start gap-2 text-sm">
          <Checkbox
            checked={context.profileSnapshot === "current"}
            onCheckedChange={(checked) =>
              setContext({ ...context, profileSnapshot: checked ? "current" : undefined })
            }
            aria-label="Include current profile snapshot"
          />
          <span>
            <span className="block font-medium">Include current profile</span>
            <span className="block text-xs text-muted-foreground">Use the current profile as a bounded draft reference.</span>
          </span>
        </label>
        <details className="rounded-lg border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-medium">Add typed references</summary>
          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="career-job-id">Job id</Label>
              <input id="career-job-id" type="number" min={1} value={context.jobId ?? ""} onChange={(event) => updateId("jobId", event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="career-resume-id">Resume version id</Label>
              <input id="career-resume-id" type="number" min={1} value={context.resumeVersionId ?? ""} onChange={(event) => updateId("resumeVersionId", event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="career-offer-ids">Offer application ids</Label>
              <input
                id="career-offer-ids"
                type="text"
                inputMode="numeric"
                placeholder="e.g. 12, 18"
                value={(context.offerApplicationIds ?? []).join(", ")}
                onChange={(event) => updateOfferIds(event.target.value)}
                className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
              />
              <p className="text-xs text-muted-foreground">Up to 10 offer-status application ids.</p>
            </div>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function SessionRail({
  sessions,
  selectedId,
  onSelect,
  showArchived,
  setShowArchived,
}: {
  sessions: ReturnType<typeof useCareerLabSessions>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  showArchived: boolean;
  setShowArchived: (value: boolean) => void;
}) {
  const rows = sessions.data?.sessions ?? [];
  return (
    <Card className="bg-card/90">
      <CardHeader className="flex-row items-center justify-between gap-2 pb-3">
        <div>
          <CardTitle className="text-base">Sessions</CardTitle>
          <CardDescription>One active draft room at a time.</CardDescription>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Toggle archived sessions" onClick={() => setShowArchived(!showArchived)}>
          {showArchived ? <ArchiveRestore aria-hidden="true" /> : <Archive aria-hidden="true" />}
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {sessions.isPending ? <Skeleton className="h-16 w-full" /> : null}
        {!sessions.isPending && rows.length === 0 ? <p className="text-sm text-muted-foreground">No saved sessions yet.</p> : null}
        {rows.map((row) => (
          <button
            type="button"
            key={row.sessionId}
            onClick={() => onSelect(row.sessionId)}
            className={cn(
              "w-full rounded-xl border p-3 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              row.sessionId === selectedId && "border-primary bg-primary/5",
            )}
          >
            <span className="block truncate text-sm font-medium">{row.goal || "Untitled Career Lab"}</span>
            <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant={row.status === "active" ? "secondary" : "outline"}>{row.status}</Badge>
              <span>{row.turnCount} turns</span>
            </span>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

export function CareerLabPage() {
  const [showArchived, setShowArchived] = useState(false);
  const sessions = useCareerLabSessions(showArchived);
  const skills = useCareerLabSkills();
  const activeSummary = sessions.data?.sessions?.find((row) => row.status === "active");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const displayedSessionId = activeSummary?.sessionId ?? selectedSessionId;
  const session = useCareerLabSession(displayedSessionId);
  const start = useStartCareerLab();
  const send = useSendCareerLabMessage();
  const end = useEndCareerLab();
  const archive = useArchiveCareerLabSession();
  const unarchive = useUnarchiveCareerLabSession();
  const remove = useDeleteCareerLabSession();
  const recoveredRun = useCareerLabRecoveredRun(displayedSessionId);
  const [streamRunId, setStreamRunId] = useState<string | null>(null);
  const [suppressedRunId, setSuppressedRunId] = useState<string | null>(null);
  const runId = streamRunId ?? (recoveredRun && recoveredRun.runId !== suppressedRunId ? recoveredRun.runId : null);
  const stream = useChatStream(runId);
  const [composer, setComposer] = useState("");
  const [skill, setSkill] = useState("");
  const [goal, setGoal] = useState("");
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

  const sendMessage = async (retry?: string) => {
    const message = (retry ?? composer).trim();
    if (!message || busy) return;
    setRunError("");
    setSelectionNotice("");
    setSelectionExchange(null);
    setRetryMessage(message);
    setSuppressedRunId(null);
    stream.reset();
    setPending({ text: message, baseline: active?.turns?.length ?? 0 });
    try {
      const launched = active
        ? await send.mutateAsync({
            sessionId: active.sessionId,
            message,
            skill: skill ? (skill as import("./use-career-lab").CareerLabSkillName) : undefined,
            context,
            onDone: (completed) => onDone(completed, message),
          })
        : await start.mutateAsync({
            message,
            goal,
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

  const currentSummary = sessions.data?.sessions?.find((row) => row.sessionId === displayedSessionId);
  const error = stream.error || runError;

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
              <span>{error || selectionNotice}</span>
              {error && retryMessage ? (
                <Button variant="outline" size="sm" onClick={() => void sendMessage(retryMessage)} disabled={busy}>
                  Retry draft
                </Button>
              ) : null}
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <main className="flex min-w-0 flex-col gap-4">
          <Card className="min-w-0 overflow-hidden rounded-2xl">
            <CardHeader className="border-b bg-muted/25 py-4">
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="size-5 text-primary" aria-hidden="true" />Draft thread</CardTitle>
              <CardDescription>{active ? active.goal || "A focused Career Lab session" : "Start with a question, then choose a skill if routing needs help."}</CardDescription>
            </CardHeader>
            <CardContent className={cn("flex flex-col gap-4 p-4 sm:p-6", CHAT_SURFACE_HEIGHT)}>
              {session.isPending && displayedSessionId ? <Skeleton className="h-full w-full" /> : null}
              {!session.isPending && !showThread ? (
                <div className="flex min-h-[22rem] flex-1 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-8 text-center">
                  <MessageCircleMore className="size-8 text-primary" aria-hidden="true" />
                  <h2 className="text-lg font-semibold">No session selected</h2>
                  <p className="max-w-md text-sm text-muted-foreground">Ask a question below to start a draft-only session. Career Lab will route it or ask you to pick a skill.</p>
                </div>
              ) : null}
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
            <div className="border-t bg-card/95 p-4 sm:p-6">
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
            </div>
          </Card>

        </main>

        <aside className="min-w-0 space-y-4" aria-label="Career Lab controls and session history">
          <ContextRail skill={skill} setSkill={setSkill} skills={skills} goal={goal} setGoal={setGoal} context={context} setContext={setContext} skillRef={skillRef} />
          <SessionRail sessions={sessions} selectedId={displayedSessionId} onSelect={setSelectedSessionId} showArchived={showArchived} setShowArchived={setShowArchived} />
          {currentSummary?.status === "ended" ? (
            <div className="flex flex-wrap gap-2">
              {!currentSummary.archivedAt ? <Button variant="outline" size="sm" onClick={() => archive.mutate({ sessionId: currentSummary.sessionId })}><Archive aria-hidden="true" />Archive</Button> : <Button variant="outline" size="sm" onClick={() => unarchive.mutate({ sessionId: currentSummary.sessionId })}><ArchiveRestore aria-hidden="true" />Unarchive</Button>}
              <AlertDialog>
                <AlertDialogTrigger render={<Button variant="outline" size="sm"><Trash2 aria-hidden="true" />Delete</Button>} />
                <AlertDialogContent>
                  <AlertDialogHeader><AlertDialogTitle>Delete this session?</AlertDialogTitle><AlertDialogDescription>This removes the saved transcript from this workspace.</AlertDialogDescription></AlertDialogHeader>
                  <AlertDialogFooter><AlertDialogCancel>Keep session</AlertDialogCancel><AlertDialogAction onClick={() => { remove.mutate({ sessionId: currentSummary.sessionId }); setSelectedSessionId(null); }}>Delete session</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
