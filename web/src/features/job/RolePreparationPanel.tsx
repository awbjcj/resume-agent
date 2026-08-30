import {
  AlertTriangle,
  BookOpenCheck,
  CircleAlert,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ACTIVE_RUN_STATUSES,
  latestArtifactRun,
  useArtifactRunIndex,
} from "@/features/job/artifact-runs";
import { useRolePreparation } from "@/features/job/use-company-research";
import { useRefreshRolePreparation } from "@/features/job/use-job-mutations";
import { ResearchNotice, ResearchPanelHeader } from "./ResearchPanel";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function RolePreparationPanel({ jobId }: { jobId: number }) {
  const query = useRolePreparation(jobId);
  const refresh = useRefreshRolePreparation(jobId);
  const run = latestArtifactRun(
    useArtifactRunIndex(),
    "rolePreparation",
    "jobId",
    jobId,
  );
  const generating = Boolean(run && ACTIVE_RUN_STATUSES.includes(run.status));
  const resource = query.data;
  const brief = resource?.state === "ready" ? resource.brief : null;
  const canRefresh = resource?.canRefresh ?? false;

  return (
    <section aria-labelledby="role-preparation-title" aria-busy={generating} className="space-y-5">
      <ResearchPanelHeader
        titleId="role-preparation-title"
        icon={<BookOpenCheck className="size-5" aria-hidden="true" />}
        eyebrow="Job-specific planning"
        title="Role preparation"
        description="Turn the frozen company dossier, exact job description, selected documents, and earlier-round notes into an interview-ready brief."
        context="Generation is explicit. Existing briefs stay frozen until you regenerate them."
        action={
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
            disabled={!canRefresh || generating}
            onClick={() => refresh.mutate()}
          >
            {generating ? (
              <LoaderCircle className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {generating ? "Preparing…" : brief ? "Regenerate brief" : "Generate brief"}
          </Button>
        }
      />

      {run?.status === "failed" && (
        <ResearchNotice
          icon={<AlertTriangle className="size-4" />}
          className="border-destructive/30 bg-destructive/5 text-destructive"
          role="alert"
        >
          {run.error ?? "Role preparation failed. The last saved brief is unchanged."}
        </ResearchNotice>
      )}

      {query.isPending ? (
        <Card className="p-5 text-sm text-muted-foreground">Loading role preparation…</Card>
      ) : brief ? (
        <div className="space-y-5">
          <Card className="gap-0 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">
                Company research v{brief.companyIntelligenceVersionNumber}
              </Badge>
              {brief.resumeVersionId && (
                <Badge variant="outline">Resume v{brief.resumeVersionId}</Badge>
              )}
              {resource?.state === "ready" && resource.inputsChanged && (
                <Badge variant="outline">Inputs changed</Badge>
              )}
              <span className="text-xs text-muted-foreground">
                Generated {formatDate(brief.generatedAt)}
              </span>
            </div>
            <p className="mt-4 text-[15px] leading-7">{brief.positioningSummary}</p>
          </Card>

          {resource?.state === "ready" && resource.inputsChanged && (
            <ResearchNotice
              icon={<AlertTriangle className="size-4" />}
              className="border-amber-300/60 bg-amber-50/70 text-amber-950 dark:border-amber-800 dark:bg-amber-950/25 dark:text-amber-100"
            >
              The job, selected documents, company dossier, or interview notes changed after this brief was generated. The saved brief remains unchanged until you regenerate it.
            </ResearchNotice>
          )}

          {(brief.priorRoundFocus ?? []).length > 0 && (
            <Card className="gap-0 p-5">
              <h3 className="font-heading text-lg font-semibold">Earlier-round focus</h3>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
                {(brief.priorRoundFocus ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="gap-0 p-5">
              <h3 className="font-heading text-lg font-semibold">Priority competencies</h3>
              <ul className="mt-4 space-y-4">
                {(brief.competencies ?? []).map((item) => (
                  <li key={item.name}>
                    <p className="font-semibold">{item.name}</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.rationale}</p>
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="gap-0 p-5">
              <h3 className="font-heading text-lg font-semibold">Concerns to prepare</h3>
              <ul className="mt-4 space-y-4">
                {(brief.concerns ?? []).map((item) => (
                  <li key={item.concern}>
                    <p className="font-semibold">{item.concern}</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.preparation}</p>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card className="gap-0 p-5">
            <h3 className="font-heading text-lg font-semibold">Likely questions</h3>
            <ol className="mt-4 space-y-5">
              {(brief.likelyQuestions ?? []).map((item, index) => (
                <li key={`${item.question}-${index}`} className="border-t pt-4 first:border-0 first:pt-0">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">{item.questionType.replaceAll("_", " ")}</Badge>
                    {item.competency && <Badge variant="secondary">{item.competency}</Badge>}
                  </div>
                  <p className="mt-2 font-semibold leading-6">{item.question}</p>
                  {item.rationale && <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.rationale}</p>}
                  {item.storyPrompt && (
                    <p className="mt-2 text-sm leading-6"><span className="font-semibold">Story prompt: </span>{item.storyPrompt}</p>
                  )}
                </li>
              ))}
            </ol>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            {[
              ["Questions to ask", brief.questionsToAsk ?? []],
              ["Recruiter verification", brief.recruiterVerificationQuestions ?? []],
            ].map(([title, items]) => (
              <Card key={String(title)} className="gap-0 p-5">
                <h3 className="font-heading text-lg font-semibold">{String(title)}</h3>
                <ul className="mt-4 space-y-4">
                  {(items as NonNullable<typeof brief.questionsToAsk>).map((item) => (
                    <li key={item.text}>
                      <p className="font-semibold leading-6">{item.text}</p>
                      {item.rationale && <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.rationale}</p>}
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>

          <ResearchNotice
            icon={<CircleAlert className="size-4" />}
            className="border-border bg-muted/40 text-muted-foreground"
          >
            {brief.caveat}
          </ResearchNotice>
        </div>
      ) : (
        <Card className="items-center gap-0 border-dashed px-6 py-10 text-center shadow-none">
          <BookOpenCheck className="size-8 text-muted-foreground" aria-hidden="true" />
          <h3 className="mt-3 text-base font-semibold">No role brief yet</h3>
          <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
            {resource?.message ?? "Generate company research first, then build a role-specific brief."}
          </p>
        </Card>
      )}
    </section>
  );
}
