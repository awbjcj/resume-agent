import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { rateConfidence } from "./chart-theme";

export function RateLabel({ count, total }: { count: number; total: number }) {
  const { t } = useTranslation();
  const confidence = rateConfidence(total);
  const percentage = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5 tabular-nums">
      <span>{t("analytics.rate.count", { count, total })}</span>
      {confidence !== "suppressed" ? (
        <span className={cn(confidence === "low" && "text-muted-foreground")}>
          {percentage}%
        </span>
      ) : null}
      <span className="text-xs text-muted-foreground">{t("analytics.rate.sample", { count: total })}</span>
    </span>
  );
}
