import { useMemo, useState } from "react";
import { Building2, ChevronRight, Layers3, Tags } from "lucide-react";

import { CHAT_SURFACE_HEIGHT } from "@/components/chat/layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { ProposalCard } from "./ProposalCard";
import { canAddProposal, groupProposals } from "./proposals";
import { useApproveScoutProposal, type ScoutProposal } from "./use-scout";

function Section({ title, icon, rows, defaultOpen, children }: { title: string; icon: React.ReactNode; rows: number; defaultOpen: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!rows) return null;
  return (
    <section>
      <h3>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="sticky top-0 z-10 flex w-full items-center gap-2 border-b bg-background/95 px-3 py-2 text-left backdrop-blur focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden="true" />
          {icon}
          <span className="flex-1 text-xs font-semibold tracking-wide uppercase">{title}</span>
          <Badge variant="secondary" className="px-1.5 py-0 text-[10px] leading-4 tabular-nums">{rows}</Badge>
        </button>
      </h3>
      {open ? <ul>{children}</ul> : null}
    </section>
  );
}

/** The proposal ledger.
 *
 * Grouped and internally scrolled rather than a flat stack of cards: a research
 * turn can land eight proposals and a session can accumulate dozens, and the
 * old rail grew the whole page for each one. The scroll region is bounded to the
 * conversation's height, so the page length no longer depends on how productive
 * the Scout was.
 */
export function ProposalRail({ sessionId, proposals, scrapeAvailable, className }: { sessionId: string; proposals: ScoutProposal[]; scrapeAvailable: boolean; className?: string }) {
  const approve = useApproveScoutProposal();
  const [batching, setBatching] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [added, setAdded] = useState<string[]>([]);
  const [summary, setSummary] = useState("");

  const groups = useMemo(() => groupProposals(proposals, added), [proposals, added]);
  // The one predicate the row's Add button also uses, so the batch button can no
  // longer offer fewer (or more) proposals than the rows individually accept.
  const ready = useMemo(
    () => [...groups.companies, ...groups.terms].filter((row) => canAddProposal(row, scrapeAvailable)),
    [groups, scrapeAvailable],
  );
  const pendingCount = groups.companies.length + groups.terms.length;

  const addAll = async () => {
    const ids = ready.map((row) => row.id);
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

  const row = (proposal: ScoutProposal) => <ProposalCard key={proposal.id} sessionId={sessionId} proposal={proposal} scrapeAvailable={scrapeAvailable} error={errors[proposal.id]} locallyAdded={added.includes(proposal.id)} />;

  // An explicit height, not `h-full`. A grid item's `h-full` resolves against a
  // row whose height is itself derived from the tallest item's content, so with
  // twenty rows the ledger sized the row and `h-full` bounded nothing -- the
  // page grew by exactly the amount this redesign exists to remove.
  return <aside className={cn("flex flex-col", CHAT_SURFACE_HEIGHT, className)} aria-label="Scout proposals">
    <Card className="flex min-h-0 flex-1 flex-col gap-0 overflow-hidden py-0 shadow-none">
      <CardHeader className="gap-2 border-b bg-primary/5 px-3 py-3">
        <div className="flex items-center gap-2">
          <Layers3 className="size-4 shrink-0 text-primary" aria-hidden="true" />
          <CardTitle className="flex-1 text-sm">Proposal ledger</CardTitle>
          <span className="text-xs tabular-nums text-muted-foreground">{pendingCount} pending</span>
        </div>
        <Button className="w-full" size="sm" variant="secondary" disabled={!ready.length || batching} onClick={addAll} aria-label="Add all ready proposals">
          {ready.length ? `Add all ready (${ready.length})` : "Nothing ready to add"}
        </Button>
        <p aria-live="polite" className="min-h-4 text-center text-xs text-muted-foreground">{summary}</p>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-hidden p-0">
        {proposals.length ? (
          <ScrollArea className="h-full">
            <Section title="Companies" icon={<Building2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />} rows={groups.companies.length} defaultOpen>
              {groups.companies.map(row)}
            </Section>
            <Section title="Search terms" icon={<Tags className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />} rows={groups.terms.length} defaultOpen>
              {groups.terms.map(row)}
            </Section>
            <Section title="Resolved" icon={<Layers3 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />} rows={groups.resolved.length} defaultOpen={false}>
              {groups.resolved.map(row)}
            </Section>
          </ScrollArea>
        ) : (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">Proposals from your conversation will collect here.</p>
        )}
      </CardContent>
    </Card>
  </aside>;
}
