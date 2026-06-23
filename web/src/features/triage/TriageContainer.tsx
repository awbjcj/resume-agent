import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { JobModal } from "@/components/JobModal";
import { TriageCard } from "./TriageCard";
import { PrunePanel } from "./PrunePanel";
import { useTriage } from "./use-triage";
import { useArchive, useDeleteJob, useRestore } from "./use-triage-mutations";

export function TriageContainer() {
  const [archived, setArchived] = useState(false);
  const { data: rows, isLoading } = useTriage(archived);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [params, setParams] = useSearchParams();
  const archive = useArchive();
  const restore = useRestore();
  const del = useDeleteJob();

  const toggle = (id: number, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      if (on) n.add(id);
      else n.delete(id);
      return n;
    });

  if (isLoading) return <BoardSkeleton />;

  const deletable = new Set((rows ?? []).filter((r) => !r.hasProgress).map((r) => r.jobId));
  const allSelectedDeletable = selected.size > 0 && [...selected].every((id) => deletable.has(id));
  const openId = params.get("job");
  const clearSel = () => setSelected(new Set());

  return (
    <>
      <PageHeader
        kicker="Intake"
        title="Triage Desk"
        sub="Raw and rejected jobs before the shortlist. Archive noise, delete dead-ends, prune in bulk."
      />
      <div className="mb-5 inline-flex items-center gap-3 rounded-lg border bg-card px-4 py-3 shadow-[0_1px_2px_rgba(24,32,38,0.04)]">
        <Switch id="show-archived" checked={archived} onCheckedChange={setArchived} />
        <Label htmlFor="show-archived" className="text-sm font-medium">
          Show archived
        </Label>
      </div>
      <MetricRow
        items={[
          ["In view", String(rows?.length ?? 0)],
          ["Deletable", String(deletable.size)],
        ]}
      />
      <PrunePanel />
      {!rows?.length ? (
        <EmptyState
          title="Nothing to triage"
          body="Run a pull to bring in jobs, or toggle archived."
        />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3 shadow-[0_1px_2px_rgba(24,32,38,0.04)]">
            <span className="rounded-full bg-secondary px-3 py-1.5 text-sm">
              <strong>{selected.size}</strong> selected
            </span>
            {archived ? (
              <Button
                disabled={!selected.size}
                onClick={() => {
                  selected.forEach((id) => restore.mutate(id));
                  clearSel();
                }}
              >
                Restore selected
              </Button>
            ) : (
              <Button
                disabled={!selected.size}
                onClick={() => {
                  selected.forEach((id) => archive.mutate(id));
                  clearSel();
                }}
              >
                Archive selected
              </Button>
            )}
            <ConfirmDialog
              trigger={
                <Button variant="destructive" disabled={!allSelectedDeletable}>
                  Delete selected
                </Button>
              }
              title={`Delete ${selected.size} job(s)?`}
              description="This cannot be undone."
              confirmLabel="Confirm delete"
              onConfirm={() => {
                selected.forEach((id) => del.mutate(id));
                clearSel();
              }}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            {rows.map((row) => (
              <TriageCard
                key={row.jobId}
                row={row}
                checked={selected.has(row.jobId)}
                onCheck={(v) => toggle(row.jobId, v)}
                onOpen={() =>
                  setParams(
                    (p) => {
                      p.set("job", String(row.jobId));
                      return p;
                    },
                    { replace: true },
                  )
                }
              />
            ))}
          </div>
        </>
      )}
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={() =>
            setParams(
              (p) => {
                p.delete("job");
                return p;
              },
              { replace: true },
            )
          }
        />
      )}
    </>
  );
}
