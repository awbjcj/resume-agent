import { useState } from "react";
import { Archive, ArchiveRestore, EllipsisVertical, Plus, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { NewInterviewDialog } from "./NewInterviewDialog";
import {
  type InterviewSessionSummary, useArchiveInterviewSession,
  useDeleteInterviewSession, useInterviewSessions, useUnarchiveInterviewSession,
} from "./use-interview";

function SessionRow({ row, selected, onArchive, onDelete }: {
  row: InterviewSessionSummary;
  selected: boolean;
  onArchive: (row: InterviewSessionSummary) => void;
  onDelete: (row: InterviewSessionSummary) => void;
}) {
  const archive = useArchiveInterviewSession();
  const unarchive = useUnarchiveInterviewSession();
  const label = [row.company, row.title].filter(Boolean).join(" · ") || "Mock interview";
  return (
    <li className={cn("flex items-center gap-2 rounded-xl border px-3 py-2.5 transition-colors", selected && "border-primary bg-primary/5")}>
      <Link to={`/interview?session=${row.sessionId}`} className="min-w-0 flex-1 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="block truncate text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">
          {row.status === "active" ? `Question ${row.askedCount} of ${row.questionCount}` : row.overallScore != null ? `Scored ${row.overallScore}/5` : "Completed"}
          {" · "}{new Date(row.startedAt).toLocaleDateString()}
        </span>
      </Link>
      {row.archivedAt ? <Badge variant="outline">Archived</Badge> : null}
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button size="icon" variant="ghost" aria-label={`Actions for ${label}`}><EllipsisVertical /></Button>} />
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            {row.status === "ended" && !row.archivedAt ? <DropdownMenuItem onClick={() => archive.mutate({ sessionId: row.sessionId }, { onSuccess: () => onArchive(row) })}><Archive />Archive</DropdownMenuItem> : null}
            {row.archivedAt ? <DropdownMenuItem onClick={() => unarchive.mutate({ sessionId: row.sessionId })}><ArchiveRestore />Unarchive</DropdownMenuItem> : null}
            <DropdownMenuItem variant="destructive" onClick={() => onDelete(row)}><Trash2 />Delete</DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}

function SessionGroup({ title, rows, selectedId, onArchive, onDelete }: {
  title: string;
  rows: InterviewSessionSummary[];
  selectedId: string | null;
  onArchive: (row: InterviewSessionSummary) => void;
  onDelete: (row: InterviewSessionSummary) => void;
}) {
  if (!rows.length) return null;
  return <section aria-label={title} className="flex flex-col gap-2">
    <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{title}</h3>
    <ul className="flex flex-col gap-2">{rows.map((row) => <SessionRow key={row.sessionId} row={row} selected={row.sessionId === selectedId} onArchive={onArchive} onDelete={onDelete} />)}</ul>
  </section>;
}

export function SessionsRail({ selectedId }: { selectedId: string | null }) {
  const navigate = useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<InterviewSessionSummary | null>(null);
  const sessions = useInterviewSessions(undefined, showArchived);
  const remove = useDeleteInterviewSession();
  const rows = sessions.data?.sessions ?? [];

  return <aside className="flex w-full flex-col gap-4 rounded-2xl border bg-card p-4 shadow-sm lg:sticky lg:top-6 lg:w-80 lg:shrink-0">
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-base font-semibold">Sessions</h2>
      <Button size="sm" onClick={() => setNewOpen(true)}><Plus />New interview</Button>
    </div>
    {sessions.isPending ? <div className="flex flex-col gap-2" aria-label="Loading sessions"><Skeleton className="h-14" /><Skeleton className="h-14" /></div> : null}
    {sessions.isError ? <div className="flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"><p>Could not load sessions.</p><Button size="sm" variant="outline" onClick={() => void sessions.refetch()}>Try again</Button></div> : null}
    {!sessions.isPending && !sessions.isError && rows.length === 0 ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No interview sessions yet.</p> : null}
    <SessionGroup title="In progress" rows={rows.filter((row) => row.status === "active")} selectedId={selectedId} onArchive={() => undefined} onDelete={setPendingDelete} />
    <SessionGroup title="Completed" rows={rows.filter((row) => row.status === "ended")} selectedId={selectedId} onArchive={(row) => { if (row.sessionId === selectedId) navigate("/interview", { replace: true }); }} onDelete={setPendingDelete} />
    <Field orientation="horizontal">
      <Switch id="show-archived-interviews" checked={showArchived} onCheckedChange={setShowArchived} />
      <FieldLabel htmlFor="show-archived-interviews">Show archived</FieldLabel>
    </Field>
    <NewInterviewDialog open={newOpen} onOpenChange={setNewOpen} />
    <AlertDialog open={pendingDelete != null} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
      <AlertDialogContent>
        <AlertDialogHeader><AlertDialogTitle>Delete this interview?</AlertDialogTitle><AlertDialogDescription>{pendingDelete?.status === "active" ? "This interview is still in progress — deleting it abandons it without a debrief. This cannot be undone." : "The transcript and debrief will be permanently removed. This cannot be undone."}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>Keep it</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={remove.isPending} onClick={() => { if (!pendingDelete) return; const deletingSelected = pendingDelete.sessionId === selectedId; remove.mutate({ sessionId: pendingDelete.sessionId }, { onSuccess: () => { if (deletingSelected) navigate("/interview", { replace: true }); } }); setPendingDelete(null); }}>Delete</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </aside>;
}
