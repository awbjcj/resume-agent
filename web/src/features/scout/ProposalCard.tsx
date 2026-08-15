import { useId, useRef, useState } from "react";
import { ChevronRight, ExternalLink, Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  blockedReason, canAddProposal, proposalBadge, proposalDetail, proposalLabel,
} from "./proposals";
import { SourceVerificationActions } from "./SourceVerificationActions";
import {
  useApproveScoutProposal,
  useDismissScoutProposal,
  useResolveScoutProposal,
  type ScoutProposal,
} from "./use-scout";

export { proposalBadge, proposalLabel } from "./proposals";

/** One ledger row.
 *
 * Deliberately a dense two-line row rather than a card: the rail has to stay
 * readable at twenty-plus pending proposals, and a stack of full cards pushed
 * the page metres tall. Detail (full reason, evidence links, failure text) is
 * revealed in place, so scanning stays cheap and deciding stays possible.
 */
export function ProposalCard({ sessionId, proposal, scrapeAvailable, error, locallyAdded = false }: { sessionId: string; proposal: ScoutProposal; scrapeAvailable: boolean; error?: string; locallyAdded?: boolean }) {
  const approve = useApproveScoutProposal();
  const dismiss = useDismissScoutProposal();
  const resolve = useResolveScoutProposal();
  const [open, setOpen] = useState(false);
  const [editingReason, setEditingReason] = useState(false);
  const [reason, setReason] = useState("");
  const dismissButton = useRef<HTMLButtonElement>(null);
  const detailId = useId();

  const label = proposalLabel(proposal);
  const detail = proposalDetail(proposal);
  const pending = proposal.status === "pending" && !locallyAdded;
  const normalAddable = canAddProposal(proposal);
  const addDisabled = !pending || !normalAddable || approve.isPending;
  const blocked = pending ? blockedReason(proposal, scrapeAvailable) : "";
  const citations = (proposal.citations ?? []).filter((item) => /^https?:\/\//i.test(item.url));
  // The dismissal editor lives in the detail region, so opening it must open the
  // region -- otherwise clicking Dismiss on a collapsed row does nothing visible.
  // An error forces it open for the same reason: a batch run reports "N failed"
  // in the header, and the row that explains which and why must not be hidden
  // behind a disclosure the user has no reason to suspect.
  const expanded = open || editingReason || Boolean(error);

  return (
    <Collapsible
      open={expanded}
      onOpenChange={setOpen}
      render={<li className={cn("scout-proposal-card border-b border-border/60 last:border-b-0", !pending && "bg-muted/30")} data-pending={pending} />}
    >
      {/* The disclosure button holds the chevron and the label and nothing else,
          so its accessible name is exactly the proposal's name. Folding the
          badges and reason into it instead made every row announce as one long
          run-on string and collide with the "Add {label}" control beside it. */}
      <div className="flex items-start gap-1.5 px-3 pt-2.5">
        <CollapsibleTrigger
          aria-controls={detailId}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-sm py-0.5 text-left focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform duration-[160ms] ease-out-strong motion-reduce:transition-none", expanded && "rotate-90")} aria-hidden="true" />
          <span className={cn("truncate text-sm font-medium leading-tight", !pending && "text-muted-foreground")}>{label}</span>
        </CollapsibleTrigger>
        {pending ? (
          <div className="flex shrink-0 items-center gap-0.5">
            <Button ref={dismissButton} size="icon-sm" variant="ghost" aria-label={`Dismiss ${label}`} onClick={() => { setEditingReason(true); setOpen(true); }}><X /></Button>
            {normalAddable ? <Button size="icon-sm" aria-label={`Add ${label}`} disabled={addDisabled} onClick={() => { void approve.mutateAsync({ sessionId, proposalId: proposal.id }).catch(() => undefined); }}><Plus /></Button> : null}
          </div>
        ) : null}
      </div>
      {/* Meta only while collapsed. The reason is the longest thing a row can
          carry and rendering it on every row cost roughly double the height,
          which is the density problem the redesign is for -- it moves into the
          detail region, one click away. */}
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 px-3 pb-2.5 pl-8">
        <Badge variant="outline" className="px-1.5 py-0 text-[10px] leading-4 font-medium">{locallyAdded ? "Added" : proposalBadge(proposal)}</Badge>
        {detail ? <span className="truncate text-[11px] capitalize text-muted-foreground">{detail}</span> : null}
        {proposal.fitScore != null ? <span className="text-[11px] tabular-nums text-muted-foreground">{proposal.fitScore}% fit</span> : null}
      </div>
      <CollapsibleContent keepMounted id={detailId} className="translate-y-0 space-y-2 overflow-hidden px-3 pb-3 pl-8 text-xs opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity">
        {proposal.reason ? <p className="leading-relaxed text-muted-foreground">{proposal.reason}</p> : null}
        {proposal.source?.url && proposal.check === "validated" ? <a href={proposal.source.canonicalBoardUrl || proposal.source.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 font-medium text-primary underline-offset-4 hover:underline"><span className="truncate">{proposal.source.canonicalBoardUrl || proposal.source.url}</span><ExternalLink className="size-3 shrink-0" aria-hidden="true" /></a> : null}
        {citations.length ? <div className="flex flex-wrap gap-2">{citations.map((item) => <a key={item.url} href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline">{item.title || "Evidence"}<ExternalLink className="size-3" aria-hidden="true" /></a>)}</div> : null}
        {proposal.source?.evidence?.length ? <div className="space-y-1 text-muted-foreground"><p className="font-medium text-foreground">Verification evidence</p>{proposal.source.evidence.map((item, index) => <p key={`${item.kind}-${item.sourceUrl}-${index}`}>{item.summary || item.kind.replaceAll("_", " ")}</p>)}</div> : null}
        {proposal.source?.searchedFamilies?.length ? <p className="text-muted-foreground">Checked: {proposal.source.searchedFamilies.join(", ")}</p> : null}
        {proposal.source?.unsearchedFamilies?.length ? <p className="text-muted-foreground">Not checked: {proposal.source.unsearchedFamilies.join(", ")}</p> : null}
        {proposal.checkError ? <p className="text-destructive">{proposal.checkError}</p> : null}
        {proposal.dismissReason ? <p className="text-muted-foreground">Dismissed: {proposal.dismissReason}</p> : null}
        {blocked ? <p className="text-muted-foreground">{blocked}</p> : null}
        {pending && proposal.kind === "source" ? <SourceVerificationActions proposal={proposal} scrapeAvailable={scrapeAvailable} resolvePending={resolve.isPending} confirmPending={approve.isPending} onResolve={(url) => resolve.mutateAsync({ sessionId, proposalId: proposal.id, url })} onConfirm={() => approve.mutateAsync({ sessionId, proposalId: proposal.id, manualConfirmation: true })} /> : null}
        {error ? <p role="alert" className="text-destructive">{error}</p> : null}
        {pending && editingReason ? (
          <div className="space-y-2">
            <label className="block font-medium" htmlFor={`dismiss-${proposal.id}`}>Reason for dismissing {label}</label>
            <Input id={`dismiss-${proposal.id}`} maxLength={200} value={reason} onChange={(event) => setReason(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") { setEditingReason(false); queueMicrotask(() => dismissButton.current?.focus()); } }} />
            <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setEditingReason(false)}>Cancel</Button><Button size="sm" variant="secondary" disabled={dismiss.isPending} onClick={() => { void dismiss.mutateAsync({ sessionId, proposalId: proposal.id, reason: reason.trim() }).then(() => setEditingReason(false)).catch(() => undefined); }}>Confirm dismiss</Button></div>
          </div>
        ) : null}
      </CollapsibleContent>
    </Collapsible>
  );
}
