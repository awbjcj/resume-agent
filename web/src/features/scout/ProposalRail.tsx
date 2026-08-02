import { useMemo, useState } from "react";
import { Layers3 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ProposalCard } from "./ProposalCard";
import { useApproveScoutProposal, type ScoutProposal } from "./use-scout";

export function ProposalRail({ sessionId, proposals, scrapeAvailable, className }: { sessionId: string; proposals: ScoutProposal[]; scrapeAvailable: boolean; className?: string }) {
  const approve = useApproveScoutProposal();
  const [batching, setBatching] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [added, setAdded] = useState<string[]>([]);
  const [summary, setSummary] = useState("");
  const ordered = useMemo(() => [...proposals].sort((a, b) => Number(a.status !== "pending") - Number(b.status !== "pending")), [proposals]);
  const validated = ordered.filter((row) => row.status === "pending" && row.check === "validated");

  const addAll = async () => {
    const ids = validated.map((row) => row.id);
    let successes = 0;
    const failures: Record<string, string> = {};
    setBatching(true);
    for (const proposalId of ids) {
      try { await approve.mutateAsync({ sessionId, proposalId }); setAdded((current) => [...current, proposalId]); successes += 1; }
      catch (caught) { failures[proposalId] = caught instanceof Error ? caught.message : "Could not add"; }
    }
    setErrors(failures);
    setSummary(`${successes} added, ${Object.keys(failures).length} failed`);
    setBatching(false);
  };

  return <aside className={cn("space-y-3", className)} aria-label="Scout proposals">
    <Card className="border-primary/20 bg-primary/5 shadow-none"><CardHeader className="pb-3"><div className="flex items-center gap-2"><Layers3 className="size-4 text-primary" aria-hidden="true" /><CardTitle className="text-base">Proposal ledger</CardTitle></div><CardDescription>Review each discovery before it changes your workspace.</CardDescription></CardHeader><CardContent><Button className="w-full" variant="secondary" disabled={!validated.length || batching} onClick={addAll}>Add all validated</Button><p aria-live="polite" className="mt-2 text-center text-xs text-muted-foreground">{summary}</p></CardContent></Card>
    {ordered.length ? ordered.map((proposal) => <ProposalCard key={proposal.id} sessionId={sessionId} proposal={proposal} scrapeAvailable={scrapeAvailable} error={errors[proposal.id]} locallyAdded={added.includes(proposal.id)} />) : <Card className="border-dashed shadow-none"><CardContent className="py-8 text-center text-sm text-muted-foreground">Proposals from your conversation will collect here.</CardContent></Card>}
  </aside>;
}
