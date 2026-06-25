import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";

type BulkResult = { affected: number; skipped: number; reasons: Record<string, number> };

export function BulkPreviewButton({
  label,
  title,
  confirmLabel,
  variant = "outline",
  preview,
  run,
}: {
  label: string;
  title: string;
  confirmLabel?: string;
  variant?: "default" | "outline" | "destructive" | "secondary" | "ghost";
  preview: () => Promise<BulkResult>;
  run: () => Promise<BulkResult>;
}) {
  const [result, setResult] = useState<BulkResult | null>(null);
  const [loading, setLoading] = useState(false);

  return (
    <ConfirmDialog
      trigger={
        <Button
          variant={variant}
          size="sm"
          onClick={() => {
            setResult(null);
            setLoading(true);
            preview()
              .then(setResult)
              .finally(() => setLoading(false));
          }}
        >
          {label}
        </Button>
      }
      title={title}
      description={
        loading || !result
          ? "Fetching preview count..."
          : `${result.affected.toLocaleString()} job(s) affected${
              result.skipped ? ` · ${result.skipped.toLocaleString()} skipped` : ""
            }.`
      }
      confirmLabel={confirmLabel ?? label}
      confirmDisabled={loading || !result}
      onConfirm={run}
    />
  );
}
