import { AlertTriangle, Building2, LoaderCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { JobDetail } from "@/features/job/use-job-detail";
import {
  ACTIVE_RUN_STATUSES,
  latestArtifactRun,
  useArtifactRunIndex,
} from "@/features/job/artifact-runs";
import { useRefreshCompanyIntelligence } from "@/features/job/use-job-mutations";
import { CompanyIntelligenceEvidence } from "./CompanyIntelligenceEvidence";
import { ResearchNotice, ResearchPanelHeader } from "./ResearchPanel";

export function CompanyIntelligencePanel({
  jobId,
  company,
  initialResult,
}: {
  jobId: number;
  company: string | null;
  initialResult?: JobDetail["companyIntelligence"];
}) {
  const refresh = useRefreshCompanyIntelligence(jobId);
  const runIndex = useArtifactRunIndex();
  const run = latestArtifactRun(
    runIndex,
    "companyIntelligence",
    "jobId",
    jobId,
  );
  const researching = Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
  const failed = run?.status === "failed";
  const result = initialResult ?? null;
  const evidence = result?.state === "ready" ? result.evidence : null;
  const canRefresh = result?.canRefresh ?? Boolean(company?.trim());
  const isStale = result?.state === "ready" ? result.isStale : false;
  const buttonLabel = researching
    ? "Researching…"
    : evidence
      ? "Refresh research"
      : "Research company";

  return (
    <section
      aria-labelledby="company-intelligence-title"
      aria-busy={researching}
      className="space-y-5"
    >
      <ResearchPanelHeader
        titleId="company-intelligence-title"
        icon={<Building2 className="size-5" aria-hidden="true" />}
        eyebrow="Cited employer dossier"
        title="Company intelligence"
        description="Public evidence about strategy, recent moves, culture, challenges, and competitive position. Refreshes are always explicit."
        context={
          company?.trim()
            ? "Refreshing updates every job at this company."
            : undefined
        }
        action={
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            disabled={!canRefresh || researching}
            aria-label={`${buttonLabel}${company ? ` for ${company}` : ""}`}
            onClick={() => refresh.mutate()}
          >
            {researching ? (
              <LoaderCircle className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {buttonLabel}
          </Button>
        }
      />

      <span className="sr-only" aria-live="polite">
        {researching ? "Researching…" : ""}
      </span>

      {failed && (
        <ResearchNotice
          icon={<AlertTriangle className="size-4" />}
          className="border-destructive/30 bg-destructive/5 text-destructive"
          role="alert"
        >
          {run?.error ??
            "Company research failed. The last saved dossier is unchanged."}
        </ResearchNotice>
      )}

      {evidence ? (
        <CompanyIntelligenceEvidence evidence={evidence} isStale={isStale} />
      ) : (
        <Card className="items-center gap-0 border-dashed px-6 py-12 text-center shadow-none">
          <Building2 className="size-8 text-muted-foreground" aria-hidden="true" />
          <h3 className="mt-3 text-base font-semibold">No company dossier yet</h3>
          <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
            {result?.message ??
              (company?.trim()
                ? "Run research to build a cited company brief."
                : "Add a company name before running research.")}
          </p>
        </Card>
      )}
    </section>
  );
}
