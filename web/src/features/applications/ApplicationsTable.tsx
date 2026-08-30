import { Link } from "react-router-dom";
import { useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCalendarDate } from "@/lib/calendar-date";
import {
  ApplicationTimelineStage,
  applicationModalityLabel,
  applicationPlatformLabel,
  applicationResultLabel,
  applicationStageLabel,
  applicationStatusLabel,
} from "./application-labels";
import type { ApplicationsTableData } from "./use-applications";

type PivotCell = ApplicationsTableData["rows"][number]["cells"][string];

const FIXED_STAGES = [
  ApplicationTimelineStage.ApplicationSubmitted,
  ApplicationTimelineStage.RecruiterScreen,
  ApplicationTimelineStage.OnlineAssessment,
  ApplicationTimelineStage.Questionnaire,
  ApplicationTimelineStage.TechnicalPhoneScreen,
] as const;

const LATE_STAGES = [
  ApplicationTimelineStage.SystemDesign,
  ApplicationTimelineStage.Behavioral,
  ApplicationTimelineStage.HiringManager,
  ApplicationTimelineStage.OnsiteLoop,
  ApplicationTimelineStage.TeamMatch,
  ApplicationTimelineStage.OfferReceived,
  ApplicationTimelineStage.Rejected,
  ApplicationTimelineStage.Withdrawn,
] as const;

function compactDate(value: string, allDay = false): string {
  return formatCalendarDate(value, allDay, { month: "short", day: "numeric" });
}

function metadata(t: TFunction, cell: PivotCell): string {
  return [
    applicationResultLabel(t, cell.result),
    cell.modality ? applicationModalityLabel(t, cell.modality) : null,
    cell.platform ? applicationPlatformLabel(t, cell.platform) : null,
    cell.platformOther,
    cell.interviewers,
  ].filter(Boolean).join(" · ");
}

function StageCell({ cell, label }: { cell?: PivotCell; label: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!cell?.occurredAt) return <span className="text-muted-foreground">—</span>;
  const detail = metadata(t, cell);
  return (
    <span className="relative block w-fit">
      <button
        type="button"
        aria-label={t("applicationTimeline.details", { stage: label })}
        aria-expanded={open}
        title={detail}
        className="cursor-pointer rounded px-1 py-0.5 tabular-nums outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen((value) => !value)}
      >
        {compactDate(cell.occurredAt, cell.allDay)}
      </button>
      {open ? (
        <span className="absolute left-0 top-full z-20 mt-1 w-max max-w-64 rounded-md border bg-popover px-2.5 py-2 text-xs leading-5 text-popover-foreground shadow-card-raised">
          {detail || t("applicationTimeline.noAdditionalDetails")}
        </span>
      ) : null}
    </span>
  );
}

export function ApplicationsTable({ table }: { table: ApplicationsTableData }) {
  const { t } = useTranslation();
  if (table.rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/20 px-5 py-10 text-center text-sm text-muted-foreground">
        {t("applicationTimeline.empty")}
      </div>
    );
  }

  const technicalStageLabel = (index: number) => t("applicationTimeline.technicalRound", { number: index + 1 });
  const technicalStages = Array.from(
    { length: table.technicalRoundColumns },
    (_, index) => `technical_round_${index + 1}`,
  );
  const stages = [...FIXED_STAGES, ...technicalStages, ...LATE_STAGES];

  return (
    <div className="min-w-0 overflow-x-auto rounded-lg border bg-card shadow-card">
      <Table className="min-w-[1180px] caption-top">
        <caption className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {t("applicationTimeline.headers.caption")}
        </caption>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 z-10 min-w-44 bg-card">{t("applicationTimeline.headers.company")}</TableHead>
            <TableHead className="min-w-44">{t("applicationTimeline.headers.role")}</TableHead>
            <TableHead>{t("applicationTimeline.headers.status")}</TableHead>
            {stages.map((key) => (
              <TableHead key={key}>
                {key.startsWith("technical_round_")
                  ? technicalStageLabel(Number(key.slice("technical_round_".length)) - 1)
                  : applicationStageLabel(t, key)}
              </TableHead>
            ))}
            <TableHead>{t("applicationTimeline.headers.deadline")}</TableHead>
            <TableHead>{t("applicationTimeline.headers.totalComp")}</TableHead>
            <TableHead>{t("applicationTimeline.headers.other")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {table.rows.map((row) => (
            <TableRow key={row.jobId}>
              <TableCell className="sticky left-0 z-[1] max-w-52 bg-card font-medium">
                <Link
                  to={`/pipeline?job=${row.jobId}`}
                  className="block truncate text-primary underline-offset-4 hover:underline"
                >
                  {row.company || t("applicationTimeline.unknownCompany")}
                </Link>
              </TableCell>
              <TableCell className="max-w-56 truncate">{row.title || "—"}</TableCell>
              <TableCell><Badge variant="outline">{applicationStatusLabel(t, row.status)}</Badge></TableCell>
              {stages.map((key) => {
                const isLastVisibleRound = key === `technical_round_${table.technicalRoundColumns}`;
                return (
                  <TableCell key={key} className="whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <StageCell
                        cell={row.cells[key]}
                        label={
                          key.startsWith("technical_round_")
                            ? t("applicationTimeline.technicalRoundDetails", { number: key.slice("technical_round_".length) })
                            : applicationStageLabel(t, key)
                        }
                      />
                      {isLastVisibleRound && row.overflowRounds > 0 ? (
                        <Badge variant="secondary">+{row.overflowRounds}</Badge>
                      ) : null}
                    </div>
                  </TableCell>
                );
              })}
              <TableCell className="whitespace-nowrap">
                {row.offerDeadline
                  ? compactDate(row.offerDeadline, row.cells.offer_deadline?.allDay)
                  : "—"}
              </TableCell>
              <TableCell className="whitespace-nowrap tabular-nums">
                {row.totalComp != null
                  ? `${row.totalComp.toLocaleString()} ${row.compCurrency ?? ""}`.trim()
                  : "—"}
              </TableCell>
              <TableCell>{row.customCount ? t("applicationTimeline.otherCount", { count: row.customCount }) : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
