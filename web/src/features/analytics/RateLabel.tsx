import { cn } from "@/lib/utils";
import { rateConfidence } from "./chart-theme";

export function RateLabel({ count, total }: { count: number; total: number }) {
  const confidence = rateConfidence(total);
  const percentage = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5 tabular-nums">
      <span>{count} of {total}</span>
      {confidence !== "suppressed" ? (
        <span className={cn(confidence === "low" && "text-muted-foreground")}>
          {percentage}%
        </span>
      ) : null}
      <span className="text-xs text-muted-foreground">n={total}</span>
    </span>
  );
}
