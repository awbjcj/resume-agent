import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export function BulkActionBar({
  count,
  isAllMatching,
  pageCount,
  total,
  onSelectAllMatching,
  onClear,
  children,
}: {
  count: number;
  isAllMatching: boolean;
  pageCount: number;
  total: number;
  onSelectAllMatching: () => void;
  onClear: () => void;
  children: ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div className="mb-4 rounded-lg border bg-card shadow-sm">
      <div className="flex flex-wrap items-center gap-2 p-3">
        <span className="rounded-full bg-secondary px-3 py-1 text-sm">
          <strong>{count.toLocaleString()}</strong> selected
        </span>
        {children}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>
          Clear
        </Button>
      </div>
      {!isAllMatching && count === pageCount && total > pageCount && (
        <>
          <Separator />
          <div className="bg-primary/5 px-3 py-2 text-sm text-primary">
            All {pageCount.toLocaleString()} loaded selected.{" "}
            <Button
              variant="link"
              size="sm"
              className="h-auto px-1 py-0"
              onClick={onSelectAllMatching}
            >
              Select all {total.toLocaleString()} matching this filter
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
