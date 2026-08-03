import { BadgeCheck, CircleAlert, CircleX, LoaderCircle, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useCheckH1BSponsorship,
  type H1BSponsorship,
} from "@/features/job/use-job-mutations";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

type H1BStatus = components["schemas"]["H1BSponsorshipEvidenceOut"]["status"];

const STATUS_LABEL: Record<H1BStatus, string> = {
  matched: "History match",
  no_match: "No match",
  unavailable: "Unavailable",
};

function resultStatus(result: H1BSponsorship | undefined): H1BStatus | null {
  return result?.evidence?.status ?? null;
}

export function H1BCheckButton({
  jobId,
  company,
  initialStatus,
}: {
  jobId: number;
  company?: string | null;
  initialStatus?: H1BStatus | null;
}) {
  const check = useCheckH1BSponsorship(jobId);
  const status = resultStatus(check.data) ?? initialStatus ?? null;
  const disabledCapability = check.data?.capability === "disabled";
  const unavailableCapability = check.data?.capability === "unavailable";
  const disabled = !company?.trim() || check.isPending || disabledCapability;
  const label = check.isPending
    ? "Checking…"
    : disabledCapability
      ? "H-1B disabled"
      : unavailableCapability && !status
        ? "Unavailable"
        : status
          ? STATUS_LABEL[status]
          : "Check H-1B";
  const accessibleLabel = !company?.trim()
    ? "Check H-1B sponsorship (company missing)"
    : status
      ? `Check H-1B sponsorship again; current result: ${STATUS_LABEL[status]}`
      : "Check H-1B sponsorship";

  return (
    <Button
      type="button"
      size="xs"
      variant={status === "matched" ? "secondary" : "outline"}
      className={cn(
        "max-w-[9.5rem] text-xs",
        status === "matched" && "text-emerald-700 dark:text-emerald-300",
        status === "no_match" && "text-rose-700 dark:text-rose-300",
        status === "unavailable" && "text-muted-foreground",
      )}
      aria-label={accessibleLabel}
      title={accessibleLabel}
      disabled={disabled}
      onClick={() => check.mutate()}
    >
      {check.isPending ? (
        <LoaderCircle className="animate-spin" aria-hidden="true" />
      ) : status === "matched" ? (
        <BadgeCheck aria-hidden="true" />
      ) : status === "no_match" ? (
        <CircleX aria-hidden="true" />
      ) : disabledCapability ? (
        <CircleAlert aria-hidden="true" />
      ) : (
        <ShieldCheck aria-hidden="true" />
      )}
      <span className="truncate">{label}</span>
    </Button>
  );
}
