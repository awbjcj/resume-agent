import { useState } from "react";
import { HistoryIcon, RefreshCw, Undo2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function RefreshClustersButton({
  unassignedCount,
  onRegroup,
  onMaintain,
  canUndo,
  onUndo,
  maintenanceDue,
  trailing,
}: {
  unassignedCount: number;
  onRegroup: () => Promise<boolean>;
  onMaintain: () => Promise<boolean>;
  canUndo: boolean;
  onUndo: () => Promise<boolean>;
  maintenanceDue: boolean;
  trailing?: React.ReactNode;
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
    <div className="relative flex items-center gap-2">
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
        {busy === "regroup" ? "Regrouping…" : `Regroup unassigned (${unassignedCount})`}
      </Button>

      {/* Named for what it does. This action merges, splits, renames and
          reparents *domains*; it cannot assign an unassigned skill, and
          calling it "Maintain taxonomy" next to Regroup implied it could.
          Its variant mirrors Regroup's: default (filled) when due, so the
          button itself carries the urgency signal a status line used to. */}
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant={maintenanceDue ? "default" : "outline"}
              size="sm"
              disabled={busy !== null}
              onClick={() => void start("maintain", onMaintain)}
            />
          }
        >
          <HistoryIcon data-icon="inline-start" />
          {busy === "maintain" ? "Reorganizing…" : "Reorganize domains"}
        </TooltipTrigger>
        <TooltipContent>
          Merges, splits, renames and recategorizes domains. Doesn't assign
          unassigned skills — use Regroup for that.
        </TooltipContent>
      </Tooltip>

      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null || !canUndo}
        onClick={() => void start("undo", onUndo)}
      >
        <Undo2Icon data-icon="inline-start" />
        {busy === "undo" ? "Restoring…" : "Undo last reorganize"}
      </Button>

      {trailing}

      {/* Absolutely positioned so a transient failure never pushes the row
          onto a second line — the steady-state toolbar always stays flush. */}
      {failed !== null && (
        <span
          role="status"
          className="absolute top-full right-0 mt-1.5 animate-in fade-in slide-in-from-top-1 text-xs text-nowrap text-destructive duration-150 ease-out-strong motion-reduce:animate-none"
        >
          Couldn't start taxonomy {failed}.
        </span>
      )}
    </div>
  );
}
