import { useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, Clock3, History, Sparkles, Trash2 } from "lucide-react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatThread, type ChatThreadMessage } from "@/components/chat/ChatThread";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { useChatStream } from "@/lib/chat/useChatStream";
import type { RunRecord } from "@/lib/runs/store";
import { useRunStore } from "@/lib/runs/store";
import { ProposalRail } from "./ProposalRail";
import {
  useArchiveScoutSession, useDeleteScoutSession, useEndScoutSession,
  useScoutSession, useScoutSessions, useSendScoutMessage, useStartScoutSession,
  useUnarchiveScoutSession, type ScoutSessionSummary,
} from "./use-scout";

function SessionHistory({ rows, selected, onSelect }: { rows: ScoutSessionSummary[]; selected: string | null; onSelect: (id: string) => void }) {
  const archive = useArchiveScoutSession();
  const unarchive = useUnarchiveScoutSession();
  const remove = useDeleteScoutSession();
  if (!rows.length) return null;
  return <Card className="shadow-none"><CardHeader><div className="flex items-center gap-2"><History className="size-4" aria-hidden="true" /><CardTitle className="text-base">Session history</CardTitle></div></CardHeader><CardContent><ul className="divide-y">{rows.map((row) => <li key={row.sessionId} className="flex flex-wrap items-center gap-2 py-3"><button className="min-w-0 flex-1 text-left" onClick={() => onSelect(row.sessionId)}><span className="block truncate text-sm font-medium">{row.goal}</span><span className="text-xs text-muted-foreground">{row.proposalCount} proposals · {row.addedCount} added</span></button>{selected === row.sessionId ? <Badge variant="outline">Viewing</Badge> : null}{row.status === "ended" && !row.archivedAt ? <Button size="icon-sm" variant="ghost" aria-label={`Archive ${row.goal}`} onClick={() => archive.mutate({ sessionId: row.sessionId })}><Archive /></Button> : null}{row.archivedAt ? <Button size="icon-sm" variant="ghost" aria-label={`Unarchive ${row.goal}`} onClick={() => unarchive.mutate({ sessionId: row.sessionId })}><ArchiveRestore /></Button> : null}<Button size="icon-sm" variant="ghost" aria-label={`Delete ${row.goal}`} onClick={() => { if (window.confirm(`Delete Scout session “${row.goal}”?`)) remove.mutate({ sessionId: row.sessionId }); }}><Trash2 /></Button></li>)}</ul></CardContent></Card>;
}

export function ScoutPage() {
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
  const [localFirstMessage, setLocalFirstMessage] = useState("");
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
    if (!active && localFirstMessage) return [{ id: "local-first", role: "user", parts: [{ kind: "text", text: localFirstMessage }] }];
    return durable;
  }, [active, localFirstMessage]);

  const launchMessage = async (message = composer.trim()) => {
    if (!message || busy) return;
    setLastMessage(message); setRunError(""); setSuppressedRunId(null); stream.reset();
    try {
      if (!active) {
        setLocalFirstMessage(message); setStreamBaseline(0);
        const run = await start.mutateAsync({ message, onDone: (done: RunRecord) => {
          if (ignoredRuns.current.delete(done.runId)) return;
          setStreamRunId(null);
          if (done.status === "succeeded") { const result = done.result as { sessionId?: string } | null; if (result?.sessionId) setSelectedId(result.sessionId); setLocalFirstMessage(""); setComposer(""); }
          else setRunError(done.error ?? "Scout could not start");
        } });
        setStreamRunId(run.runId);
      } else {
        setStreamBaseline(durableTurns);
        const run = await send.mutateAsync({ sessionId: active.sessionId, message, onDone: (done: RunRecord) => { if (ignoredRuns.current.delete(done.runId)) return; setStreamRunId(null); if (done.status === "succeeded") setComposer(""); else setRunError(done.error ?? "Scout could not reply"); } });
        setStreamRunId(run.runId);
      }
    } catch (caught) { setRunError(caught instanceof Error ? caught.message : "Scout request failed"); }
  };

  const stop = () => { if (attachedRunId) ignoredRuns.current.add(attachedRunId); setSuppressedRunId(attachedRunId); setStreamRunId(null); stream.stop(); setLocalFirstMessage(""); setRunError(""); };
  const endSession = async () => {
    if (!active || busy) return;
    setStreamBaseline(durableTurns); setRunError(""); stream.reset();
    try { const run = await end.mutateAsync({ sessionId: active.sessionId, onDone: (done: RunRecord) => { if (ignoredRuns.current.delete(done.runId)) return; setStreamRunId(null); if (done.status !== "succeeded") setRunError(done.error ?? "Could not end session"); } }); setStreamRunId(run.runId); }
    catch (caught) { setRunError(caught instanceof Error ? caught.message : "Could not end session"); }
  };

  if (sessions.isLoading || (displayedId && session.isLoading)) return <div className="space-y-4"><Skeleton className="h-20" /><Skeleton className="h-[34rem]" /></div>;
  if (sessions.isError || (displayedId && session.isError)) return <Alert variant="destructive"><AlertTitle>Discovery Scout is unavailable</AlertTitle><AlertDescription><Button variant="outline" size="sm" onClick={() => { void sessions.refetch(); void session.refetch(); }}>Try again</Button></AlertDescription></Alert>;
  const rows = sessions.data?.sessions ?? [];

  return <div className="mx-auto max-w-[1480px] space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary"><Sparkles className="size-4" aria-hidden="true" />Guided discovery</div><h1 className="text-2xl font-semibold tracking-tight">Discovery Scout</h1><p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">Talk through the companies, roles, locations, and boundaries that should shape your search. Nothing is added until you approve it.</p></div><div className="flex items-center gap-2">{active?.status === "active" ? <Button variant="outline" disabled={busy} onClick={endSession}>End session</Button> : active ? <Button variant="outline" onClick={() => setSelectedId(null)}>New session</Button> : null}</div></header>
    {runError || stream.error ? <Alert variant="destructive"><AlertTitle>The Scout could not finish that step</AlertTitle><AlertDescription className="flex flex-wrap items-center gap-3"><span className="flex-1">{runError || stream.error}</span><Button size="sm" variant="outline" onClick={() => launchMessage(lastMessage)}>Retry</Button></AlertDescription></Alert> : null}
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="min-w-0 overflow-hidden"><CardHeader className="border-b"><div className="flex items-center gap-2"><Bot className="size-5 text-primary" aria-hidden="true" /><CardTitle>{active?.goal || "Plan your next search"}</CardTitle></div><CardDescription>{active ? <><Clock3 className="mr-1 inline size-3.5" />{active.status === "active" ? "Conversation active" : "Session ended"}</> : "Try: Find remote healthcare platform roles at growing mid-size companies."}</CardDescription></CardHeader><CardContent className="flex h-[36rem] flex-col gap-4 p-4"><ChatThread messages={messages} streaming={streaming?.length ? streaming : null} showReasoning />{active?.recap ? <div className="rounded-xl border bg-muted/35 p-3 text-sm"><span className="font-medium">Recap: </span>{active.recap}</div> : null}{active?.status !== "ended" ? <ChatComposer value={composer} onChange={setComposer} onSend={() => launchMessage()} onStop={stop} busy={busy} ariaLabel="Discovery request" placeholder={active ? "Ask for a change…" : "Find remote healthcare platform roles at growing mid-size companies…"} /> : <p className="rounded-xl bg-muted/50 p-3 text-center text-sm text-muted-foreground">This conversation has ended. Pending proposals remain available to review.</p>}</CardContent></Card>
      <ProposalRail className="min-w-0 xl:sticky xl:top-24" sessionId={active?.sessionId ?? ""} proposals={active?.proposals ?? []} scrapeAvailable={active?.scrapeAvailable ?? false} />
    </div>
    <div className="flex items-center gap-2"><Checkbox id="scout-archived" checked={showArchived} onCheckedChange={(checked) => setShowArchived(Boolean(checked))} /><label htmlFor="scout-archived" className="text-sm">Show archived sessions</label></div>
    <SessionHistory rows={rows.filter((row) => row.sessionId !== active?.sessionId)} selected={displayedId} onSelect={setSelectedId} />
  </div>;
}
