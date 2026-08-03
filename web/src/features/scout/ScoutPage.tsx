import { useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, Building2, CheckCircle2, Clock3, Compass, MessageCircleQuestion, Pencil, Search, Trash2 } from "lucide-react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
import { GuidedWorkspaceHeader } from "@/components/chat/GuidedWorkspaceHeader";
import { CHAT_PAGE_WIDTH, CHAT_SURFACE_HEIGHT } from "@/components/chat/layout";
import { WorkspaceEmptyState } from "@/components/chat/WorkspaceEmptyState";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
  useRenameScoutSession, useUnarchiveScoutSession, type ScoutSessionSummary,
} from "./use-scout";

function SessionHistory({ rows, selected, onSelect, showArchived, onShowArchivedChange }: { rows: ScoutSessionSummary[]; selected: string | null; onSelect: (id: string) => void; showArchived: boolean; onShowArchivedChange: (checked: boolean) => void }) {
  const archive = useArchiveScoutSession();
  const unarchive = useUnarchiveScoutSession();
  const remove = useDeleteScoutSession();
  const rename = useRenameScoutSession();
  const [pendingDelete, setPendingDelete] = useState<ScoutSessionSummary | null>(null);
  const [pendingRename, setPendingRename] = useState<ScoutSessionSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  return <Card className="rounded-2xl shadow-none">
    <CardHeader className="gap-3 border-b">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2"><Clock3 className="size-4 text-primary" aria-hidden="true" /><CardTitle className="text-base">Session history</CardTitle></div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground"><Checkbox checked={showArchived} onCheckedChange={(checked) => onShowArchivedChange(Boolean(checked))} />Show archived</label>
      </div>
    </CardHeader>
    <CardContent>
      {rows.length ? <ul className="divide-y">{rows.map((row) => <li key={row.sessionId} className="flex flex-wrap items-center gap-2 py-3">
        <button className="min-w-0 flex-1 rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelect(row.sessionId)}><span className="block truncate text-sm font-medium">{row.sessionTitle || row.goal}</span><span className="text-xs text-muted-foreground">{row.proposalCount} proposals · {row.addedCount} added</span></button>
        {selected === row.sessionId ? <Badge variant="outline">Viewing</Badge> : null}
        <Button size="icon-sm" variant="ghost" aria-label={`Rename ${row.sessionTitle || row.goal}`} onClick={() => { setPendingRename(row); setRenameTitle(row.sessionTitle || row.goal); }}><Pencil /></Button>
        {row.status === "ended" && !row.archivedAt ? <Button size="icon-sm" variant="ghost" aria-label={`Archive ${row.goal}`} onClick={() => archive.mutate({ sessionId: row.sessionId })}><Archive /></Button> : null}
        {row.archivedAt ? <Button size="icon-sm" variant="ghost" aria-label={`Unarchive ${row.goal}`} onClick={() => unarchive.mutate({ sessionId: row.sessionId })}><ArchiveRestore /></Button> : null}
        <Button size="icon-sm" variant="ghost" aria-label={`Delete ${row.goal}`} onClick={() => setPendingDelete(row)}><Trash2 /></Button>
      </li>)}</ul> : <p className="py-3 text-sm text-muted-foreground">No previous Scout sessions.</p>}
    </CardContent>
    <Dialog open={pendingRename != null} onOpenChange={(open) => { if (!open) setPendingRename(null); }}><DialogContent><DialogHeader><DialogTitle>Rename Scout session</DialogTitle><DialogDescription>Choose a short name for this research thread.</DialogDescription></DialogHeader><Input aria-label="Session title" autoFocus maxLength={120} value={renameTitle} onChange={(event) => setRenameTitle(event.target.value)} /><DialogFooter><Button variant="ghost" onClick={() => setPendingRename(null)}>Cancel</Button><Button disabled={!renameTitle.trim() || rename.isPending} onClick={() => { if (!pendingRename) return; rename.mutate({ sessionId: pendingRename.sessionId, title: renameTitle.trim() }, { onSuccess: () => setPendingRename(null) }); }}>Save title</Button></DialogFooter></DialogContent></Dialog>
    <AlertDialog open={pendingDelete != null} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Delete this Scout session?</AlertDialogTitle><AlertDialogDescription>The conversation and its proposal history will be permanently removed. This cannot be undone.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Keep it</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={() => { if (!pendingDelete) return; remove.mutate({ sessionId: pendingDelete.sessionId }); setPendingDelete(null); }}>Delete</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
  </Card>;
}

export function ScoutPage() {
  const [newOpen, setNewOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const sessions = useScoutSessions(showArchived);
  const activeSummary = sessions.data?.sessions?.find((row) => row.status === "active");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const displayedId = activeSummary?.sessionId ?? selectedId;
  const session = useScoutSession(displayedId);
  const start = useStartScoutSession();
  const send = useSendScoutMessage();
  const end = useEndScoutSession();
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
    <SessionHistory rows={rows.filter((row) => row.sessionId !== active?.sessionId)} selected={displayedId} onSelect={setSelectedId} showArchived={showArchived} onShowArchivedChange={setShowArchived} />
    <Dialog open={newOpen} onOpenChange={setNewOpen}><DialogContent><DialogHeader><DialogTitle>Create Scout session</DialogTitle><DialogDescription>Describe the search you want to explore. You can refine it throughout the conversation.</DialogDescription></DialogHeader><Input aria-label="Discovery goal" autoFocus value={composer} onChange={(event) => setComposer(event.target.value)} placeholder="Find remote healthcare platform roles…" /><DialogFooter><Button variant="ghost" onClick={() => setNewOpen(false)}>Cancel</Button><Button disabled={!composer.trim() || busy} onClick={() => { setNewOpen(false); void launchMessage(); }}><Building2 aria-hidden="true" />Start research</Button></DialogFooter></DialogContent></Dialog>
  </div>;
}
