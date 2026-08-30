import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { applicationStatusLabel } from "./application-labels";
import type { RoleComparison } from "./use-role-comparison";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

type Item = RoleComparison["items"][number];

function companyEvidence(t: TFunction, item: Item): string {
  const evidence = item.companyEvidence;
  if (evidence.state !== "ready") {
    return t("applications.comparison.notResearched");
  }
  const verification = evidence.strongestVerification
    ? t(`applications.comparison.verification.${evidence.strongestVerification}`)
    : t("applications.comparison.noClaims");
  const depth = evidence.researchDepth
    ? t(`applications.comparison.depth.${evidence.researchDepth}`)
    : t("applications.comparison.unknownDepth");
  return t("applications.comparison.evidenceSummary", {
    depth,
    count: evidence.sourceCount ?? 0,
    verification,
    freshness: t(
      evidence.isStale
        ? "applications.comparison.stale"
        : "applications.comparison.current",
    ),
  });
}

function sponsorship(t: TFunction, status: Item["h1BStatus"]): string {
  if (status === "matched") {
    return t("applications.comparison.sponsorship.matched");
  }
  if (status === "no_match") {
    return t("applications.comparison.sponsorship.noMatch");
  }
  if (status === "unavailable") {
    return t("applications.comparison.sponsorship.unavailable");
  }
  return t("applications.comparison.sponsorship.notChecked");
}

export function RoleComparisonTable({ comparison }: { comparison: RoleComparison }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="role-comparison-title" className="space-y-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
          {t("applications.comparison.kicker")}
        </p>
        <h2 id="role-comparison-title" className="mt-1 text-lg font-semibold">
          {t("applications.comparison.title")}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("applications.comparison.description")}
        </p>
      </div>
      <div className="min-w-0 overflow-x-auto rounded-lg border bg-card shadow-card">
        <Table className="min-w-[980px]">
          <TableHeader>
            <TableRow>
              <TableHead>{t("applications.comparison.headers.role")}</TableHead>
              <TableHead>{t("applications.comparison.headers.fit")}</TableHead>
              <TableHead>{t("applications.comparison.headers.stage")}</TableHead>
              <TableHead>
                {t("applications.comparison.headers.companyEvidence")}
              </TableHead>
              <TableHead>{t("applications.comparison.headers.h1bEvidence")}</TableHead>
              <TableHead>{t("applications.comparison.headers.latestOffer")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparison.items.map((item) => (
              <TableRow key={item.jobId}>
                <TableCell className="min-w-56">
                  <p className="font-medium">
                    {item.company || t("applicationTimeline.unknownCompany")}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {item.title || t("applications.comparison.unknownRole")}
                  </p>
                </TableCell>
                <TableCell className="tabular-nums">
                  {item.fitScore == null
                    ? t("applications.comparison.notScored")
                    : `${item.fitScore}%`}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {applicationStatusLabel(t, item.applicationStatus)}
                  </Badge>
                </TableCell>
                <TableCell className="min-w-72 text-sm">
                  {companyEvidence(t, item)}
                </TableCell>
                <TableCell className="min-w-44 text-sm">
                  {sponsorship(t, item.h1BStatus)}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {item.offerTotal == null
                    ? t("applications.comparison.noStructuredOffer")
                    : `${item.offerTotal.toLocaleString()} ${item.offerCurrency ?? ""}`.trim()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
