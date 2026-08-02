import { useRef, useState } from "react";
import { ExternalLink, Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useApproveScoutProposal, useDismissScoutProposal, type ScoutProposal } from "./use-scout";

export function proposalBadge(row: ScoutProposal): string {
  if (row.status === "added") return "Added";
  if (row.status === "dismissed") return "Dismissed";
  if (row.check === "validated") return row.source?.roleCount == null ? "Validated" : `${row.source.roleCount} roles`;
  if (row.check === "unverified") return "Scrape target";
  if (row.check === "duplicate") return "Already in sources";
  if (row.check === "avoid") return "Avoid";
  if (row.check === "failed") return "Failed";
  return "New";
}

export function proposalLabel(row: ScoutProposal) {
  return row.source?.company ?? row.term?.value ?? "Proposal";
}

export function ProposalCard({ sessionId, proposal, scrapeAvailable, error, locallyAdded = false }: { sessionId: string; proposal: ScoutProposal; scrapeAvailable: boolean; error?: string; locallyAdded?: boolean }) {
  const approve = useApproveScoutProposal();
  const dismiss = useDismissScoutProposal();
  const [editingReason, setEditingReason] = useState(false);
  const [reason, setReason] = useState("");
  const dismissButton = useRef<HTMLButtonElement>(null);
  const label = proposalLabel(proposal);
  const pending = proposal.status === "pending" && !locallyAdded;
  const blockedCheck = ["avoid", "failed", "duplicate"].includes(proposal.check) ||
    (proposal.kind === "source" && proposal.check === "new");
  const scrapeBlocked = proposal.check === "unverified" && !scrapeAvailable;
  const addDisabled = !pending || blockedCheck || scrapeBlocked || approve.isPending;
  const secondary = proposal.source?.ats ?? proposal.term?.termKind.replaceAll("_", " ");

  return (
    <Card className={cn("scout-proposal-card shadow-none", !pending && "bg-muted/35 opacity-80")} data-pending={pending}>
      <CardHeader className="space-y-2 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0"><CardTitle className="truncate text-base">{label}</CardTitle>{secondary ? <p className="mt-1 text-xs capitalize text-muted-foreground">{secondary}</p> : null}</div>
          <div className="flex flex-wrap justify-end gap-1.5"><Badge variant="outline">{locallyAdded ? "Added" : proposalBadge(proposal)}</Badge>{proposal.fitScore != null ? <Badge>{proposal.fitScore}% fit</Badge> : null}</div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="leading-relaxed text-muted-foreground">{proposal.reason}</p>
        {proposal.citations?.length ? <div className="flex flex-wrap gap-2">{proposal.citations.filter((item) => /^https?:\/\//i.test(item.url)).map((item) => <a key={item.url} href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline">{item.title || "Evidence"}<ExternalLink className="size-3" aria-hidden="true" /></a>)}</div> : null}
        {proposal.checkError ? <p className="text-xs text-destructive">{proposal.checkError}</p> : null}
        {proposal.dismissReason ? <p className="text-xs text-muted-foreground">Dismissed: {proposal.dismissReason}</p> : null}
        {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
        {scrapeBlocked ? <p className="text-xs text-muted-foreground">Browser scraping is unavailable, so this source cannot be verified and added yet.</p> : null}
        {pending ? editingReason ? (
          <div className="space-y-2">
            <label className="text-xs font-medium" htmlFor={`dismiss-${proposal.id}`}>Reason for dismissing {label}</label>
            <Input id={`dismiss-${proposal.id}`} maxLength={200} value={reason} onChange={(event) => setReason(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") { setEditingReason(false); queueMicrotask(() => dismissButton.current?.focus()); } }} />
            <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setEditingReason(false)}>Cancel</Button><Button size="sm" variant="secondary" disabled={dismiss.isPending} onClick={() => { void dismiss.mutateAsync({ sessionId, proposalId: proposal.id, reason: reason.trim() }).then(() => setEditingReason(false)).catch(() => undefined); }}>Confirm dismiss</Button></div>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <Button ref={dismissButton} size="sm" variant="ghost" aria-label={`Dismiss ${label}`} onClick={() => setEditingReason(true)}><X />Dismiss</Button>
            <Button size="sm" aria-label={`Add ${label}`} disabled={addDisabled} onClick={() => { void approve.mutateAsync({ sessionId, proposalId: proposal.id }).catch(() => undefined); }}><Plus />Add</Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
