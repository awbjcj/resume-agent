import { useState } from "react";

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
import { useCompanyIntelligenceVersions } from "@/features/job/use-company-research";
import { CompanyIntelligenceEvidence } from "./CompanyIntelligenceEvidence";
import { ResearchNotice, ResearchPanelHeader } from "./ResearchPanel";
import { RolePreparationPanel } from "./RolePreparationPanel";
import { HiringContactsPanel } from "./HiringContactsPanel";

type ResearchDepth = "quick" | "standard" | "deep";

const DEPTH_COPY: Record<ResearchDepth, string> = {
  quick: "Quick scan prioritizes the strongest official and current independent evidence.",
  standard: "Standard balances coverage and cost across every supported research axis.",
  deep: "Deep seeks corroboration, dates, and credible conflicting evidence.",
};

export function CompanyIntelligencePanel({
  jobId,
  company,
  initialResult,
}: {
  jobId: number;
  company: string | null;
  initialResult?: JobDetail["companyIntelligence"];
}) {
  const [depth, setDepth] = useState<ResearchDepth>(
    initialResult?.state === "ready" ? initialResult.evidence.researchDepth : "standard",
  );
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
  const history = useCompanyIntelligenceVersions(jobId, Boolean(evidence));
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
            ? `${DEPTH_COPY[depth]} Refreshing updates every job at this company.`
            : undefined
        }
        action={
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
            <label htmlFor="company-research-depth" className="sr-only">
              Company research depth
            </label>
            <select
              id="company-research-depth"
              value={depth}
              disabled={researching}
              onChange={(event) => setDepth(event.target.value as ResearchDepth)}
              className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
            >
              <option value="quick">Quick</option>
              <option value="standard">Standard</option>
              <option value="deep">Deep</option>
            </select>
            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              disabled={!canRefresh || researching}
              aria-label={`${buttonLabel}${company ? ` for ${company}` : ""}`}
              onClick={() => refresh.mutate(depth)}
            >
              {researching ? (
                <LoaderCircle className="animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw aria-hidden="true" />
              )}
              {buttonLabel}
            </Button>
          </div>
        }
      />

      <span className="sr-only" aria-live="polite">
        {researching ? "Researching…" : ""}
      </span>

      {failed && (
        <ResearchNotice
          icon={<AlertTriangle className="size-4" />}
          tone="danger"
          role="alert"
        >
          {run?.error ??
            "Company research failed. The last saved dossier is unchanged."}
        </ResearchNotice>
      )}

      {evidence ? (
        <CompanyIntelligenceEvidence
          evidence={evidence}
          isStale={isStale}
          history={history.data?.items ?? []}
          historyLoading={history.isPending}
        />
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

      <RolePreparationPanel jobId={jobId} />
      <HiringContactsPanel jobId={jobId} />
    </section>
  );
}
