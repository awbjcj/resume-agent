import { useState } from "react";
import { HistoryIcon, RefreshCw, Undo2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";

export function RefreshClustersButton({
  unassignedCount,
  onRegroup,
  onMaintain,
  canUndo,
  onUndo,
  generation,
  maintenanceDue,
  footer,
}: {
  unassignedCount: number;
  onRegroup: () => Promise<boolean>;
  onMaintain: () => Promise<boolean>;
  canUndo: boolean;
  onUndo: () => Promise<boolean>;
  generation: string | null | undefined;
  maintenanceDue: boolean;
  footer?: React.ReactNode;
}) {
  const [busy, setBusy] = useState<"regroup" | "maintain" | "undo" | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const start = async (
    action: "regroup" | "maintain" | "undo",
    run: () => Promise<boolean>,
  ) => {
    setBusy(action);
    setFailed(null);
    try {
      if (!(await run())) setFailed(action);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          variant={unassignedCount > 0 ? "default" : "outline"}
          size="sm"
          disabled={busy !== null || unassignedCount === 0}
          onClick={() => void start("regroup", onRegroup)}
        >
          <RefreshCw
            data-icon="inline-start"
            className={busy === "regroup" ? "animate-spin motion-reduce:animate-none" : ""}
          />
          {busy === "regroup"
            ? "Regrouping…"
            : `Regroup unassigned (${unassignedCount})`}
        </Button>
        {/* Named for what it does. This action merges, splits, renames and
            reparents *domains*; it cannot assign an unassigned skill, and
            calling it "Maintain taxonomy" next to Regroup implied it could. */}
        <Button
          variant="outline"
          size="sm"
          disabled={busy !== null}
          onClick={() => void start("maintain", onMaintain)}
          title="Merge, split, rename and recategorize domains. Does not assign unassigned skills — use Regroup for that."
        >
          <HistoryIcon data-icon="inline-start" />
          {busy === "maintain" ? "Reorganizing…" : "Reorganize domains"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy !== null || !canUndo}
          onClick={() => void start("undo", onUndo)}
        >
          <Undo2Icon data-icon="inline-start" />
          {busy === "undo" ? "Restoring…" : "Undo last reorganize"}
        </Button>
      </div>
      {failed !== null && (
        <span role="status" className="text-xs text-destructive">
          Couldn't start taxonomy {failed}.
        </span>
      )}
      <div className="flex items-center justify-end gap-2">
        {footer}
        <span className="text-right text-xs text-muted-foreground">
          {generation
            ? `Taxonomy generation ${generation.slice(0, 8)}${maintenanceDue ? " · reorganize due" : ""}`
            : maintenanceDue
              ? "Taxonomy reorganize due"
              : "No generated taxonomy version yet"}
        </span>
      </div>
    </div>
  );
}
