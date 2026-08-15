import { Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

/**
 * Select-all plus the destructive bulk action, shared by the resume-version
 * and cover-letter tabs. Rendered only when something is actually deletable,
 * so a job with a single applied artifact shows no cleanup affordance at all.
 */
export function ArtifactSelectionBar({
  noun,
  selectedCount,
  allSelected,
  onToggleAll,
  onDelete,
  disabled,
}: {
  noun: string;
  selectedCount: number;
  allSelected: boolean;
  onToggleAll: () => void;
  onDelete: () => void;
  disabled?: boolean;
}) {
  const plural = `${noun}${selectedCount === 1 ? "" : "s"}`;

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 px-3 py-2">
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <Checkbox
          checked={allSelected}
          onCheckedChange={onToggleAll}
          aria-label={`Select all deletable ${noun}s`}
        />
        {selectedCount > 0 ? `${selectedCount} selected` : "Select all"}
      </label>
      <ConfirmDialog
        trigger={
          <Button
            size="sm"
            variant="destructive"
            disabled={disabled || selectedCount === 0}
          >
            <Trash2 data-icon="inline-start" />
            Delete {selectedCount > 0 ? selectedCount : ""} selected
          </Button>
        }
        title={`Delete ${selectedCount} ${plural}?`}
        description={`The ${plural} and any rendered PDF will be removed. This cannot be undone.`}
        confirmLabel="Confirm delete"
        onConfirm={onDelete}
      />
    </div>
  );
}
