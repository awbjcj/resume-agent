import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import {
  Archive,
  ArchiveRestore,
  Bot,
  FileText,
  ListChecks,
  MessageCircleMore,
  PanelRight,
  Pencil,
  Sparkles,
  SquareCheckBig,
  Trash2,
} from "lucide-react";

import { ChatComposer } from "@/components/chat/ChatComposer";
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
  useCareerLabJobDetail,
  useCareerLabJobs,
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
  const jobs = useCareerLabJobs();
  const jobDetail = useCareerLabJobDetail(context.jobId ?? null);
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [jobSource, setJobSource] = useState("");
  const jobRows = useMemo(() => jobs.data ?? [], [jobs.data]);
  const statuses = useMemo(() => [...new Set(jobRows.map((row) => row.status))].sort(), [jobRows]);
  const sources = useMemo(() => [...new Set(jobRows.map((row) => row.source))].sort(), [jobRows]);
  const filteredJobs = useMemo(() => {
    const query = jobSearch.trim().toLocaleLowerCase();
    const matches = jobRows.filter((row) => {
      const haystack = [row.company, row.title, row.location].filter(Boolean).join(" ").toLocaleLowerCase();
      return (!query || haystack.includes(query)) && (!jobStatus || row.status === jobStatus) && (!jobSource || row.source === jobSource);
    });
    const selected = jobRows.find((row) => row.jobId === context.jobId);
    return selected && !matches.some((row) => row.jobId === selected.jobId) ? [selected, ...matches] : matches;
  }, [context.jobId, jobRows, jobSearch, jobSource, jobStatus]);
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
          <summary className="cursor-pointer text-sm font-medium">Add job &amp; resume context</summary>
          <div className="mt-3 space-y-3">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2 lg:col-span-1 xl:col-span-2">
                <Label htmlFor="career-job-search">Find a job</Label>
                <Input id="career-job-search" value={jobSearch} onChange={(event) => setJobSearch(event.target.value)} placeholder="Company, role, or location" className="h-9" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="career-job-status">Job status</Label>
                <select id="career-job-status" value={jobStatus} onChange={(event) => setJobStatus(event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm">
                  <option value="">All statuses</option>
                  {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="career-job-source">Job source</Label>
                <select id="career-job-source" value={jobSource} onChange={(event) => setJobSource(event.target.value)} className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm">
                  <option value="">All sources</option>
                  {sources.map((source) => <option key={source} value={source}>{source}</option>)}
                </select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="career-job">Job</Label>
              <select
                id="career-job"
                value={context.jobId ?? ""}
                onChange={(event) => setContext({ ...context, jobId: event.target.value ? Number(event.target.value) : undefined, resumeVersionId: undefined })}
                className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm"
              >
                <option value="">No job selected</option>
                {filteredJobs.map((row) => <option key={row.jobId} value={row.jobId}>{[row.company, row.title].filter(Boolean).join(" · ") || `Job ${row.jobId}`} — {row.status}</option>)}
              </select>
              {jobs.isPending ? <p className="text-xs text-muted-foreground">Loading jobs…</p> : null}
              {jobs.isError ? <p className="text-xs text-destructive">Jobs could not be loaded.</p> : null}
              {!jobs.isPending && !jobs.isError && filteredJobs.length === 0 ? <p className="text-xs text-muted-foreground">No jobs match these filters.</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="career-resume-version">Resume version</Label>
              <select
                id="career-resume-version"
                disabled={!context.jobId || jobDetail.isPending}
                value={context.resumeVersionId ?? ""}
                onChange={(event) => setContext({ ...context, resumeVersionId: event.target.value ? Number(event.target.value) : undefined })}
                className="h-9 w-full rounded-lg border border-input bg-background px-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="">{context.jobId ? "No resume version" : "Choose a job first"}</option>
                {(jobDetail.data?.resumeVersions ?? []).map((version) => <option key={version.id} value={version.id}>Round {version.round} · {version.origin}</option>)}
              </select>
              {context.jobId && jobDetail.data?.resumeVersions.length === 0 ? <p className="text-xs text-muted-foreground">This job has no tailored resume versions yet.</p> : null}
            </div>
          </div>
        </details>
        <details className="rounded-lg border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-medium">Add offer comparison references</summary>
          <div className="mt-3">
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
  onRename,
  renamePending,
  onArchive,
  onUnarchive,
  onDelete,
}: {
  sessions: ReturnType<typeof useCareerLabSessions>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  showArchived: boolean;
  setShowArchived: (value: boolean) => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  renamePending: boolean;
  onArchive: (sessionId: string) => void;
  onUnarchive: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
}) {
  const rows = sessions.data?.sessions ?? [];
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  return (
    <Card className="bg-card/90">
      <CardHeader className="pb-3">
        <div>
          <CardTitle className="text-base">Sessions</CardTitle>
          <CardDescription>One active draft room at a time.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {sessions.isPending ? <Skeleton className="h-16 w-full" /> : null}
        {!sessions.isPending && rows.length === 0 ? <p className="text-sm text-muted-foreground">No saved sessions yet.</p> : null}
        {rows.map((row) => {
          const title = row.title || row.goal || "Untitled Career Lab";
          return (
          <div
            key={row.sessionId}
            className={cn(
              "rounded-xl border p-2 transition-colors",
              row.sessionId === selectedId && "border-primary bg-primary/5",
            )}
          >
            {editingId === row.sessionId ? (
              <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void onRename(row.sessionId, draftTitle).then(() => setEditingId(null)); }}>
                <Label htmlFor={`career-session-title-${row.sessionId}`} className="sr-only">Session title</Label>
                <Input id={`career-session-title-${row.sessionId}`} aria-label="Session title" autoFocus maxLength={120} value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} className="h-8" />
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setEditingId(null)}>Cancel</Button>
                  <Button type="submit" size="sm" disabled={!draftTitle.trim() || renamePending}>Save title</Button>
                </div>
              </form>
            ) : (
              <div className="flex items-start gap-1">
                <button type="button" onClick={() => onSelect(row.sessionId)} className="min-w-0 flex-1 rounded-lg p-1 text-left focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                  <span className="block truncate text-sm font-medium">{title}</span>
                  <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant={row.status === "active" ? "secondary" : "outline"}>{row.status}</Badge>
                    <span>{row.turnCount} turns</span>
                  </span>
                </button>
                <Button variant="ghost" size="icon-sm" aria-label={`Rename ${title}`} onClick={() => { setEditingId(row.sessionId); setDraftTitle(title); }}><Pencil aria-hidden="true" /></Button>
                {row.status === "ended" && !row.archivedAt ? <Button variant="ghost" size="icon-sm" aria-label={`Archive ${title}`} onClick={() => onArchive(row.sessionId)}><Archive aria-hidden="true" /></Button> : null}
                {row.archivedAt ? <Button variant="ghost" size="icon-sm" aria-label={`Unarchive ${title}`} onClick={() => onUnarchive(row.sessionId)}><ArchiveRestore aria-hidden="true" /></Button> : null}
                <Button variant="ghost" size="icon-sm" aria-label={`Delete ${title}`} onClick={() => onDelete(row.sessionId)}><Trash2 aria-hidden="true" /></Button>
              </div>
            )}
          </div>
        )})}
        <label className="flex items-center gap-2 pt-2 text-xs text-muted-foreground">
          <Checkbox checked={showArchived} onCheckedChange={(checked) => setShowArchived(checked === true)} />
          Show archived sessions
        </label>
      </CardContent>
    </Card>
  );
}

export function CareerLabPage() {
  const [newOpen, setNewOpen] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
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
  const rename = useRenameCareerLabSession();
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
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="size-5 text-primary" aria-hidden="true" />{active?.title || "Career Lab workspace"}</CardTitle>
              <CardDescription>{active ? active.goal || "A focused Career Lab session" : "Create a session when you are ready to work through a career question."}</CardDescription>
            </CardHeader>
            <CardContent className={cn("flex flex-col gap-4 p-4 sm:p-6", CHAT_SURFACE_HEIGHT)}>
              {session.isPending && displayedSessionId ? <Skeleton className="h-full w-full" /> : null}
              {!session.isPending && !showThread ? <WorkspaceEmptyState icon={MessageCircleMore} title="Turn a career question into a useful draft" description="Choose a skill or let Career Lab route the request. It uses only the context you select and never takes an external action." actionLabel="Create Career Lab session" onAction={() => setNewOpen(true)} steps={[{ icon: MessageCircleMore, title: "Ask one focused question", description: "Start with the decision, draft, comparison, or next step you need." }, { icon: ListChecks, title: "Choose bounded context", description: "Optionally include your profile, a job, a resume version, or offer references." }, { icon: FileText, title: "Review the draft", description: "Keep every output as a draft until you decide how to use it." }]} /> : null}
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
            {showThread ? <div className="border-t bg-card/95 p-4 sm:p-6">
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
            </div> : null}
          </Card>

        </main>

        <aside className="min-w-0 space-y-4" aria-label="Career Lab controls">
          <ContextRail skill={skill} setSkill={setSkill} skills={skills} goal={goal} setGoal={setGoal} context={context} setContext={setContext} skillRef={skillRef} />
        </aside>
      </div>
      <SessionRail sessions={sessions} selectedId={displayedSessionId} onSelect={setSelectedSessionId} showArchived={showArchived} setShowArchived={setShowArchived} renamePending={rename.isPending} onRename={async (sessionId, title) => { await rename.mutateAsync({ sessionId, title }); }} onArchive={(sessionId) => archive.mutate({ sessionId })} onUnarchive={(sessionId) => unarchive.mutate({ sessionId })} onDelete={setPendingDeleteId} />
      <Dialog open={newOpen} onOpenChange={setNewOpen}><DialogContent><DialogHeader><DialogTitle>Create Career Lab session</DialogTitle><DialogDescription>Ask for a draft, plan, comparison, or next step. The context panel remains available before and during the session.</DialogDescription></DialogHeader><Textarea aria-label="Career Lab request" autoFocus rows={4} value={composer} onChange={(event) => setComposer(event.target.value)} placeholder="Help me compare these offers and draft a decision checklist…" /><DialogFooter><Button variant="ghost" onClick={() => setNewOpen(false)}>Cancel</Button><Button disabled={!composer.trim() || busy} onClick={() => { setNewOpen(false); void sendMessage(); }}><Sparkles aria-hidden="true" />Start session</Button></DialogFooter></DialogContent></Dialog>
      <AlertDialog open={pendingDeleteId != null} onOpenChange={(open) => { if (!open) setPendingDeleteId(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Delete this session?</AlertDialogTitle><AlertDialogDescription>This permanently removes the saved transcript from this workspace.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Keep session</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={() => { if (!pendingDeleteId) return; const deletingSelected = pendingDeleteId === displayedSessionId; remove.mutate({ sessionId: pendingDeleteId }, { onSuccess: () => { if (deletingSelected) setSelectedSessionId(null); } }); setPendingDeleteId(null); }}>Delete session</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </div>
  );
}
