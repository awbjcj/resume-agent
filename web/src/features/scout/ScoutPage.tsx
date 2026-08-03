import { useMemo, useRef, useState } from "react";
import { Bot, Building2, CheckCircle2, Clock3, Compass, MessageCircleQuestion, Search } from "lucide-react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatSessionHistory, type ChatSessionHistoryItem } from "@/components/chat/ChatSessionHistory";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
import { GuidedWorkspaceHeader } from "@/components/chat/GuidedWorkspaceHeader";
import { CHAT_PAGE_WIDTH, CHAT_SURFACE_HEIGHT } from "@/components/chat/layout";
import { WorkspaceEmptyState } from "@/components/chat/WorkspaceEmptyState";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useChatStream } from "@/lib/chat/useChatStream";
import { cn } from "@/lib/utils";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { ProposalRail } from "./ProposalRail";
import {
  useArchiveScoutSession, useDeleteScoutSession, useEndScoutSession,
  useScoutSession, useScoutSessions, useSendScoutMessage, useStartScoutSession,
  useRenameScoutSession, useUnarchiveScoutSession,
} from "./use-scout";

export function ScoutPage() {
  const [newOpen, setNewOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const sessions = useScoutSessions(showArchived);
  const activeSummary = sessions.data?.sessions?.find((row) => row.status === "active");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const displayedId = selectedId ?? activeSummary?.sessionId ?? null;
  const session = useScoutSession(displayedId);
  const start = useStartScoutSession();
  const send = useSendScoutMessage();
  const end = useEndScoutSession();
  const archive = useArchiveScoutSession();
  const unarchive = useUnarchiveScoutSession();
  const remove = useDeleteScoutSession();
  const rename = useRenameScoutSession();
  const [composer, setComposer] = useState("");
  const [lastMessage, setLastMessage] = useState("");
  // The turn only reaches the durable transcript when the run finishes, so
  // without a local echo the user's own message is invisible for the whole
  // research round -- it just sits in the composer. `baseline` is the turn
  // count at launch: the echo retires the moment the persisted thread passes
  // it, which is also what stops it double-rendering after the refetch.
  const [pending, setPending] = useState<{ text: string; baseline: number } | null>(null);
  const [runError, setRunError] = useState("");
  const [streamRunId, setStreamRunId] = useState<string | null>(null);
  const [streamBaseline, setStreamBaseline] = useState(0);
  const [suppressedRunId, setSuppressedRunId] = useState<string | null>(null);
  const ignoredRuns = useRef(new Set<string>());
  const recovered = useRunStore((state) => Object.values(state.runs).find((run) =>
    ["scout-start", "scout-turn", "scout-end"].includes(run.kind) &&
    ["queued", "running", "cancelling"].includes(run.status) &&
    (run.kind === "scout-start" || run.meta?.sessionId === displayedId),
  )) ?? null;
  const recoveredId = recovered?.runId !== suppressedRunId ? recovered?.runId ?? null : null;
  const attachedRunId = streamRunId ?? recoveredId;
  const baseline = streamRunId ? streamBaseline : typeof recovered?.meta?.turnCount === "number" ? recovered.meta.turnCount : 0;
  const stream = useChatStream(attachedRunId);
  const active = session.data;
  const durableTurns = active?.turns?.length ?? 0;
  const streaming = durableTurns > baseline ? null : stream.parts;
  const busy = Boolean(attachedRunId && stream.status !== "done" && stream.status !== "error") || start.isPending || send.isPending || end.isPending;

  const messages: ChatThreadMessage[] = useMemo(() => {
    const durable = (active?.turns ?? []).map((turn, index): ChatThreadMessage => ({ id: `${turn.at}-${index}`, role: turn.role === "scout" ? "assistant" : "user", parts: [{ kind: "text", text: turn.text }, ...(turn.notice ? [{ kind: "notice" as const, message: turn.notice }] : [])] }));
    if (!pending || durableTurns > pending.baseline) return durable;
    return [...durable, { id: "pending-user", role: "user", parts: [{ kind: "text", text: pending.text }] }];
  }, [active, durableTurns, pending]);

  const launchMessage = async (message = composer.trim()) => {
    if (!message || busy) return;
    setLastMessage(message); setRunError(""); setSuppressedRunId(null); stream.reset();
    setPending({ text: message, baseline: durableTurns });
    try {
      if (!active) {
        setStreamBaseline(0);
        const run = await start.mutateAsync({ message, onDone: (done: RunRecord) => {
          if (ignoredRuns.current.delete(done.runId)) return;
          setStreamRunId(null); setPending(null);
          if (done.status === "succeeded") { const result = done.result as { sessionId?: string } | null; if (result?.sessionId) setSelectedId(result.sessionId); setComposer(""); }
          else setRunError(done.error ?? "Scout could not start");
        } });
        setStreamRunId(run.runId);
      } else {
        setStreamBaseline(durableTurns);
        const run = await send.mutateAsync({ sessionId: active.sessionId, message, onDone: (done: RunRecord) => { if (ignoredRuns.current.delete(done.runId)) return; setStreamRunId(null); setPending(null); if (done.status === "succeeded") setComposer(""); else setRunError(done.error ?? "Scout could not reply"); } });
        setStreamRunId(run.runId);
      }
    } catch (caught) { setPending(null); setRunError(caught instanceof Error ? caught.message : "Scout request failed"); }
  };

  const stop = () => { if (attachedRunId) ignoredRuns.current.add(attachedRunId); setSuppressedRunId(attachedRunId); setStreamRunId(null); stream.stop(); setPending(null); setRunError(""); };
  const endSession = async () => {
    if (!active || busy) return;
    setStreamBaseline(durableTurns); setRunError(""); stream.reset();
    try { const run = await end.mutateAsync({ sessionId: active.sessionId, onDone: (done: RunRecord) => { if (ignoredRuns.current.delete(done.runId)) return; setStreamRunId(null); if (done.status !== "succeeded") setRunError(done.error ?? "Could not end session"); } }); setStreamRunId(run.runId); }
    catch (caught) { setRunError(caught instanceof Error ? caught.message : "Could not end session"); }
  };

  if (sessions.isLoading || (displayedId && session.isLoading)) return <div className="space-y-4"><Skeleton className="h-20" /><Skeleton className="h-[34rem]" /></div>;
  if (sessions.isError || (displayedId && session.isError)) return <Alert variant="destructive"><AlertTitle>Discovery Scout is unavailable</AlertTitle><AlertDescription><Button variant="outline" size="sm" onClick={() => { void sessions.refetch(); void session.refetch(); }}>Try again</Button></AlertDescription></Alert>;
  const rows = sessions.data?.sessions ?? [];
  const historyItems: ChatSessionHistoryItem[] = rows.map((row) => ({
    id: row.sessionId,
    title: row.sessionTitle || row.goal || "Untitled Scout session",
    detail: `${row.status === "active" ? "Researching" : "Completed"} · ${row.proposalCount} proposals · ${row.addedCount} added · ${new Date(row.startedAt).toLocaleDateString()}`,
    status: row.status,
    archived: Boolean(row.archivedAt),
  }));
  const pendingProposals = active?.proposals?.filter((proposal) => proposal.status === "pending").length ?? 0;
  const addedProposals = active?.proposals?.filter((proposal) => proposal.status === "added").length ?? 0;

  return <div className={cn("space-y-6", CHAT_PAGE_WIDTH)}>
    <GuidedWorkspaceHeader
      tone="scout"
      icon={<Compass />}
      eyebrow="Guided discovery"
      title="Discovery Scout"
      description="Talk through the companies, roles, locations, and boundaries that should shape your search. Nothing is added until you approve it."
      meta={<><Badge variant={active?.status === "active" ? "secondary" : "outline"}>{active?.status === "active" ? "Scout researching" : active ? "Session complete" : "Ready to explore"}</Badge>{active ? <Badge variant="outline">{pendingProposals} pending</Badge> : null}{active ? <Badge variant="outline">{addedProposals} added</Badge> : null}</>}
      actions={active?.status === "active" ? <Button variant="outline" disabled={busy} onClick={endSession}>End session</Button> : active ? <Button variant="outline" onClick={() => setSelectedId(null)}>New session</Button> : undefined}
    />
    {runError || stream.error ? <Alert variant="destructive"><AlertTitle>The Scout could not finish that step</AlertTitle><AlertDescription className="flex flex-wrap items-center gap-3"><span className="flex-1">{runError || stream.error}</span><Button size="sm" variant="outline" onClick={() => launchMessage(lastMessage)}>Retry</Button></AlertDescription></Alert> : null}
    {/* items-stretch (the default) rather than items-start: the ledger sizes
        itself to the conversation and scrolls internally, so the page length no
        longer grows with the proposal count. */}
    <div className={cn("grid gap-6", active && "xl:grid-cols-[minmax(0,1fr)_24rem]")}>
      <Card className="min-w-0 overflow-hidden rounded-2xl">
        <CardHeader className="border-b bg-muted/20"><div className="flex items-center gap-2"><Bot className="size-5 text-primary" aria-hidden="true" /><CardTitle>{active?.sessionTitle || active?.goal || "Discovery workspace"}</CardTitle></div><CardDescription>{active ? <><Clock3 className="mr-1 inline size-3.5" />{active.status === "active" ? "Conversation active" : "Session ended"}</> : "Create a session when you are ready to shape the next search."}</CardDescription></CardHeader>
        <CardContent className={cn("flex flex-col gap-4 p-4", CHAT_SURFACE_HEIGHT)}>
          {!active && !busy ? <WorkspaceEmptyState icon={Compass} title="Shape a smarter search" description="Tell the Scout what you want to find. It will research companies and search terms, then wait for your approval before changing anything." actionLabel="Create Scout session" onAction={() => setNewOpen(true)} steps={[{ icon: MessageCircleQuestion, title: "Describe the search", description: "Share roles, locations, industries, and boundaries in plain language." }, { icon: Search, title: "Review the research", description: "The Scout returns separate, cited proposals instead of changing settings silently." }, { icon: CheckCircle2, title: "Approve what fits", description: "Add or dismiss each company and search term while keeping full control." }]} /> : <ChatThread messages={messages} streaming={streaming?.length ? streaming : null} streamingActive={stream.status === "streaming"} showReasoning assistantName="Discovery Scout" assistantIcon={<Compass className="size-4" aria-hidden="true" />} />}
          {active?.recap ? <div className="rounded-xl border bg-muted/35 p-3 text-sm"><span className="font-medium">Recap: </span>{active.recap}</div> : null}
          {active?.status === "active" ? <ChatComposer value={composer} onChange={setComposer} onSend={() => launchMessage()} onStop={stop} busy={busy} settling={stream.status === "settled"} ariaLabel="Discovery request" placeholder="Ask for a change…" /> : active ? <p className="rounded-xl bg-muted/50 p-3 text-center text-sm text-muted-foreground">This conversation has ended. Pending proposals remain available to review.</p> : null}
        </CardContent>
      </Card>
      {active ? <ProposalRail className="min-w-0" sessionId={active.sessionId} proposals={active.proposals ?? []} scrapeAvailable={active.scrapeAvailable ?? false} /> : null}
    </div>
    <ChatSessionHistory
      ariaLabel="Discovery Scout sessions"
      items={historyItems}
      selectedId={displayedId}
      onSelect={setSelectedId}
      showArchived={showArchived}
      onShowArchivedChange={setShowArchived}
      isLoading={sessions.isPending}
      isError={sessions.isError}
      onRetry={() => void sessions.refetch()}
      emptyMessage="No Scout sessions yet. Start one when you are ready to shape your search."
      createLabel="New Scout session"
      onCreate={() => setNewOpen(true)}
      onRename={(sessionId, title) => rename.mutate({ sessionId, title })}
      onArchive={(sessionId) => archive.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedId) setSelectedId(null); } })}
      onUnarchive={(sessionId) => unarchive.mutate({ sessionId })}
      onDelete={(sessionId) => remove.mutate({ sessionId }, { onSuccess: () => { if (sessionId === displayedId) setSelectedId(null); } })}
      renamePending={rename.isPending}
      deletePending={remove.isPending}
      deleteDescription="The conversation and its proposal history will be permanently removed. This cannot be undone."
    />
    <Dialog open={newOpen} onOpenChange={setNewOpen}><DialogContent><DialogHeader><DialogTitle>Create Scout session</DialogTitle><DialogDescription>Describe the search you want to explore. You can refine it throughout the conversation.</DialogDescription></DialogHeader><Input aria-label="Discovery goal" autoFocus value={composer} onChange={(event) => setComposer(event.target.value)} placeholder="Find remote healthcare platform roles…" /><DialogFooter><Button variant="ghost" onClick={() => setNewOpen(false)}>Cancel</Button><Button disabled={!composer.trim() || busy} onClick={() => { setNewOpen(false); void launchMessage(); }}><Building2 aria-hidden="true" />Start research</Button></DialogFooter></DialogContent></Dialog>
  </div>;
}
