import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  formatCountdown,
  formatUtcClock,
  useDeepSeekPricingStatus,
} from "./deepseek-pricing";

// Off-peak reuses chart-2 (already "strong/good" in FitDial's score bands);
// peak reuses ready (already "needs attention" in the match-gap dashboard).
// No new colors — both states borrow meaning the app's palette already carries.
export function DeepSeekPricingBadge() {
  const status = useDeepSeekPricingStatus();
  if (!status) return null;
  const { period, changesAt, now, weekendOffPeak } = status;
  const isPeak = period === "peak";
  const countdown = formatCountdown(changesAt.getTime() - now.getTime());

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-4xl px-2 py-0.5 text-[10px] font-normal tabular-nums transition-colors duration-300 ease-out-strong",
              isPeak ? "bg-ready/10 text-ready" : "bg-chart-2/10 text-chart-2",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "size-1.5 shrink-0 animate-pulse rounded-full motion-reduce:animate-none",
                isPeak ? "bg-ready" : "bg-chart-2",
              )}
            />
            {isPeak ? "Peak" : "Off-peak"}
            <span className="text-muted-foreground">· {countdown}</span>
          </span>
        }
      />
      <TooltipContent side="top">
        {weekendOffPeak
          ? "Weekend billing is off-peak all day. Weekday peak hours are 01:00–04:00 and 06:00–10:00 UTC."
          : isPeak
            ? `Billing peak rates now — pricier until ${formatUtcClock(changesAt)} UTC.`
            : `Billing off-peak rates now — cheaper until ${formatUtcClock(changesAt)} UTC. Weekday peak hours: 01:00–04:00 and 06:00–10:00 UTC.`}
      </TooltipContent>
    </Tooltip>
  );
}
