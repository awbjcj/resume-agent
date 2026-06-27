import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export function RefreshClustersButton({
  stale,
  onRefresh,
}: {
  stale: boolean;
  onRefresh: () => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  return (
    <div className="flex flex-col items-end gap-1.5">
      <Button
        variant={stale ? "default" : "outline"}
        size="sm"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setFailed(false);
          try {
            setFailed(!(await onRefresh()));
          } finally {
            setBusy(false);
          }
        }}
      >
        <RefreshCw className={busy ? "animate-spin motion-reduce:animate-none" : ""} />
        {busy ? "Clustering…" : stale ? "Refresh stale clusters" : "Refresh clusters"}
      </Button>
      {failed && (
        <span role="status" className="text-xs text-destructive">
          Couldn't start cluster refresh.
        </span>
      )}
    </div>
  );
}
