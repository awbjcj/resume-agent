import { Fragment } from "react";

import { fieldLabel, salaryLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

type PipelineDetailsRow = {
  status?: string;
  rejectReason?: string | null;
  rejectCategory?: string | null;
  salaryMin?: number | null;
  salaryMax?: number | null;
  salaryCurrency?: string | null;
  seniority?: string | null;
  employmentType?: string | null;
  remotePolicy?: string | null;
  sponsorshipSignal?: string | null;
};

export function PipelineDetails({ row }: { row: PipelineDetailsRow }) {
  if (
    row.rejectReason &&
    (row.status === "rejected" ||
      row.status === "filtered" ||
      row.rejectCategory === "filtered")
  ) {
    const label =
      row.status === "filtered" || row.rejectCategory === "filtered"
        ? "Filtered"
        : "Rejected";
    return (
      <div
        className="min-w-0 truncate text-sm text-destructive"
        title={`${label}: ${row.rejectReason}`}
        aria-label={`${label}: ${row.rejectReason}`}
      >
        <span className="font-medium">{label}:</span> {row.rejectReason}
      </div>
    );
  }

  const details = [
    {
      label: "Compensation",
      value: salaryLabel(
        row.salaryMin,
        row.salaryMax,
        row.salaryCurrency ?? undefined,
      ),
      className: "font-medium text-foreground",
    },
    {
      label: "Seniority",
      value: row.seniority ? fieldLabel(row.seniority) : null,
      className: "text-muted-foreground",
    },
    {
      label: "Type",
      value: row.employmentType ? fieldLabel(row.employmentType) : null,
      className: "text-muted-foreground",
    },
    {
      label: "Work arrangement",
      value: row.remotePolicy ? fieldLabel(row.remotePolicy) : null,
      className: "text-muted-foreground",
    },
    {
      label: "Sponsorship",
      value: row.sponsorshipSignal ? fieldLabel(row.sponsorshipSignal) : null,
      className:
        row.sponsorshipSignal === "denied"
          ? "text-destructive"
          : "text-primary",
    },
  ].filter((detail) => Boolean(detail.value));

  if (!details.length) return null;

  return (
    <div
      className="flex min-w-0 items-baseline gap-1.5 overflow-hidden whitespace-nowrap"
      aria-label="Pipeline details"
    >
      {details.map((detail, index) => (
        <Fragment key={detail.label}>
          {index > 0 && (
            <span aria-hidden className="shrink-0 text-border">
              •
            </span>
          )}
          <span
            className={cn("min-w-0 truncate text-sm", detail.className)}
            title={`${detail.label}: ${detail.value}`}
          >
            <span className="sr-only">{detail.label}: </span>
            {detail.value}
          </span>
        </Fragment>
      ))}
    </div>
  );
}
