import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  CircleDashed,
  CircleX,
  FolderKanban,
  ListChecks,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { evidencePortfolioWarningLabel } from "@/i18n/profile-build-diagnostics";
import type { components } from "@/lib/api/schema";
import { useEvidencePortfolio } from "./use-evidence-portfolio";

type Requirement = components["schemas"]["PortfolioRequirementOut"];

const COMPACT_LIMITS = {
  selections: 3,
  requirements: 5,
  terms: 5,
  omissions: 2,
  excerpts: 2,
  supportedNeeds: 3,
} as const;

const COVERAGE_LABEL: Record<Requirement["coverage"], string> = {
  covered: "Supported",
  adjacent: "Related experience",
  gap: "Not shown",
};

function coverageVariant(coverage: Requirement["coverage"]) {
  if (coverage === "covered") return "secondary" as const;
  if (coverage === "gap") return "destructive" as const;
  return "outline" as const;
}

function EvidenceKindIcon({ kind }: { kind: "experience" | "project" }) {
  const Icon = kind === "experience" ? BriefcaseBusiness : FolderKanban;
  return <Icon className="size-4" aria-hidden="true" />;
}

function CoverageIcon({ coverage }: { coverage: Requirement["coverage"] }) {
  if (coverage === "covered") {
    return <Check className="size-3.5" aria-hidden="true" />;
  }
  if (coverage === "gap") {
    return <CircleX className="size-3.5" aria-hidden="true" />;
  }
  return <CircleDashed className="size-3.5" aria-hidden="true" />;
}

export function EvidencePortfolioDisclosure({
  versionId,
  available,
}: {
  versionId: number;
  available: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [showAllDetails, setShowAllDetails] = useState(false);
  const panelId = useId();
  const portfolio = useEvidencePortfolio(versionId, available && expanded);

  if (!available) return null;

  const data = portfolio.data;
  const excerpts = new Map(
    (data?.evidenceExcerpts ?? []).map((excerpt) => [excerpt.factId, excerpt]),
  );
  const requirements = data?.requirements ?? [];
  const selections = data?.selections ?? [];
  const highlightTerms = data?.highlightTerms ?? [];
  const omissions = data?.omissions ?? [];
  const outsideFactIds = data?.realizedOutsideFactIds ?? [];
  const supportedRequirements = requirements.filter(
    (requirement) => requirement.coverage === "covered",
  ).length;
  const visibleSelections = showAllDetails
    ? selections
    : selections.slice(0, COMPACT_LIMITS.selections);
  const visibleRequirements = showAllDetails
    ? requirements
    : requirements.slice(0, COMPACT_LIMITS.requirements);
  const visibleTerms = showAllDetails
    ? highlightTerms
    : highlightTerms.slice(0, COMPACT_LIMITS.terms);
  const visibleOmissions = showAllDetails
    ? omissions
    : omissions.slice(0, COMPACT_LIMITS.omissions);
  const hasHiddenDetails =
    selections.length > COMPACT_LIMITS.selections ||
    requirements.length > COMPACT_LIMITS.requirements ||
    highlightTerms.length > COMPACT_LIMITS.terms ||
    omissions.length > COMPACT_LIMITS.omissions ||
    selections.some(
      (selection) =>
        (selection.selectedFactIds?.length ?? 0) > COMPACT_LIMITS.excerpts ||
        (selection.requirementTexts?.length ?? 0) > COMPACT_LIMITS.supportedNeeds,
    );

  return (
    <div className="mt-4 border-t pt-4">
      <Button
        size="sm"
        variant="outline"
        className="h-auto w-full justify-between rounded-lg px-3 py-2.5 text-left active:scale-[0.99]"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => {
          setExpanded((value) => !value);
          if (expanded) setShowAllDetails(false);
        }}
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
            <ListChecks className="size-4" aria-hidden="true" />
          </span>
          <span className="min-w-0">
            <span className="block font-semibold">Why this experience was chosen</span>
            <span className="block text-xs font-normal text-muted-foreground">
              See the job needs this version emphasizes and the evidence used.
            </span>
          </span>
        </span>
        <ChevronDown
          className={`size-4 shrink-0 text-muted-foreground transition-transform duration-200 ease-out-strong motion-reduce:transition-none ${
            expanded ? "rotate-180" : ""
          }`}
          aria-hidden="true"
        />
      </Button>

      {expanded ? (
        <section
          id={panelId}
          aria-label="Evidence selection explanation"
          className="mt-3 overflow-hidden rounded-lg border bg-muted/20"
        >
          {portfolio.isPending ? (
            <p
              className="flex items-center gap-2 p-4 text-sm text-muted-foreground"
              role="status"
            >
              <Spinner data-icon="inline-start" />
              Loading why this version was tailored this way…
            </p>
          ) : null}
          {portfolio.isError ? (
            <p className="p-4 text-sm text-destructive" role="alert">
              Could not load the evidence explanation. {portfolio.error.message}
            </p>
          ) : null}
          {data ? (
            <div className="text-sm">
              <header className="border-b bg-background/80 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-foreground">How this version was tailored</p>
                    <p className="mt-1 max-w-2xl leading-6 text-muted-foreground">
                      {`It prioritizes ${selections.length} work or project entr${selections.length === 1 ? "y" : "ies"} that best support ${supportedRequirements} of ${requirements.length} ranked job requirement${requirements.length === 1 ? "" : "s"}.`}
                    </p>
                  </div>
                  <Badge variant="outline">
                    {data.status === "deterministic_fallback"
                      ? "Rule-based selection"
                      : data.status === "inherited"
                        ? "Inherited selection"
                        : "Planned selection"}
                  </Badge>
                </div>
                {highlightTerms.length ? (
                  <div className="mt-3 flex flex-wrap items-center gap-1.5" aria-label="Terms emphasized">
                    <span className="mr-1 text-xs font-medium text-muted-foreground">Emphasized:</span>
                    {visibleTerms.map((term) => (
                      <Badge key={term} variant="secondary">{term}</Badge>
                    ))}
                    {!showAllDetails && highlightTerms.length > visibleTerms.length ? (
                      <span className="text-xs text-muted-foreground">
                        +{highlightTerms.length - visibleTerms.length} more
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </header>

              {data.warning ? (
                <p
                  className="m-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-amber-900 dark:text-amber-200"
                  role="status"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  {evidencePortfolioWarningLabel(t, data.warning)}
                </p>
              ) : null}

              <div className="grid gap-5 p-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)]">
                <div>
                  <h4 className="font-semibold">Experience used — and why</h4>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    These are the strongest profile-backed examples for this job.
                  </p>
                  {selections.length ? (
                    <ol className="mt-3 space-y-3">
                      {visibleSelections.map((selection) => {
                        const allSelectedExcerpts = (selection.selectedFactIds ?? [])
                          .map((factId) => excerpts.get(factId))
                          .filter((excerpt) => excerpt !== undefined);
                        const selectedExcerpts = showAllDetails
                          ? allSelectedExcerpts
                          : allSelectedExcerpts.slice(0, COMPACT_LIMITS.excerpts);
                        const requirementTexts = selection.requirementTexts ?? [];
                        const visibleRequirementTexts = showAllDetails
                          ? requirementTexts
                          : requirementTexts.slice(0, COMPACT_LIMITS.supportedNeeds);
                        return (
                          <li key={selection.ownerId} className="rounded-lg border bg-background p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="inline-flex items-center gap-1.5 font-semibold capitalize">
                                <EvidenceKindIcon kind={selection.ownerKind} />
                                {selection.ownerKind} {selection.rank}
                              </span>
                              <Badge variant="outline">
                                {`Up to ${selection.bulletBudget} bullet${selection.bulletBudget === 1 ? "" : "s"}`}
                              </Badge>
                              {selection.bridge ? <Badge variant="secondary">Connects related skills</Badge> : null}
                            </div>
                            <p className="mt-2 leading-6">
                              <span className="font-medium">Why chosen: </span>
                              <span className="text-muted-foreground">{selection.rationale}</span>
                            </p>
                            {requirementTexts.length ? (
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                <span className="text-xs font-medium text-muted-foreground">Supports</span>
                                {visibleRequirementTexts.map((requirement) => (
                                  <Badge key={requirement} variant="secondary">{requirement}</Badge>
                                ))}
                                {!showAllDetails && requirementTexts.length > visibleRequirementTexts.length ? (
                                  <span className="text-xs text-muted-foreground">
                                    +{requirementTexts.length - visibleRequirementTexts.length} more
                                  </span>
                                ) : null}
                              </div>
                            ) : null}
                            {selectedExcerpts.length ? (
                              <div className="mt-3 border-l-2 border-primary/30 pl-3">
                                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                  Evidence used
                                </p>
                                <ul className="mt-1.5 space-y-1.5 leading-6">
                                  {selectedExcerpts.map((excerpt) => (
                                    <li key={excerpt.factId}>{excerpt.text}</li>
                                  ))}
                                </ul>
                                {!showAllDetails && allSelectedExcerpts.length > selectedExcerpts.length ? (
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {`+${allSelectedExcerpts.length - selectedExcerpts.length} more supporting fact${allSelectedExcerpts.length - selectedExcerpts.length === 1 ? "" : "s"}`}
                                  </p>
                                ) : null}
                              </div>
                            ) : null}
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <p className="mt-3 rounded-lg border bg-background p-3 text-muted-foreground">
                      No work or project entries were selected for this version.
                    </p>
                  )}
                  {!showAllDetails && selections.length > visibleSelections.length ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {`+${selections.length - visibleSelections.length} more selected experience entr${selections.length - visibleSelections.length === 1 ? "y" : "ies"}`}
                    </p>
                  ) : null}
                </div>

                <div className="space-y-5">
                  <div>
                    <h4 className="font-semibold">What the job asks for</h4>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      Ranked by importance, with honest coverage from your profile.
                    </p>
                    <ol className="mt-3 space-y-2">
                      {visibleRequirements.map((requirement) => (
                        <li key={`${requirement.priority}-${requirement.text}`} className="rounded-lg border bg-background p-3">
                          <div className="flex items-start gap-2">
                            <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold tabular-nums">
                              {requirement.priority}
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="font-medium leading-5">{requirement.text}</p>
                              <Badge className="mt-1.5 gap-1" variant={coverageVariant(requirement.coverage)}>
                                <CoverageIcon coverage={requirement.coverage} />
                                {COVERAGE_LABEL[requirement.coverage]}
                              </Badge>
                              {requirement.rationale ? (
                                <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{requirement.rationale}</p>
                              ) : null}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                    {!showAllDetails && requirements.length > visibleRequirements.length ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        {`+${requirements.length - visibleRequirements.length} lower-priority requirement${requirements.length - visibleRequirements.length === 1 ? "" : "s"}`}
                      </p>
                    ) : null}
                  </div>

                  {omissions.length ? (
                    <div>
                      <h4 className="font-semibold">What was left out</h4>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        Relevant space was reserved for stronger matches.
                      </p>
                      <ul className="mt-2 space-y-2">
                        {visibleOmissions.map((omission) => (
                          <li key={omission.ownerId} className="rounded-md border border-dashed bg-background/60 p-2.5 text-xs leading-5 text-muted-foreground">
                            <span className="font-medium capitalize text-foreground">Other {omission.ownerKind}: </span>
                            {omission.rationale}
                          </li>
                        ))}
                      </ul>
                      {!showAllDetails && omissions.length > visibleOmissions.length ? (
                        <p className="mt-2 text-xs text-muted-foreground">
                          {`+${omissions.length - visibleOmissions.length} more omitted entr${omissions.length - visibleOmissions.length === 1 ? "y" : "ies"}`}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>

              {outsideFactIds.length ? (
                <p className="border-t bg-background/60 px-4 py-3 text-xs leading-5 text-muted-foreground">
                  {`This revision also includes ${outsideFactIds.length} fact${outsideFactIds.length === 1 ? "" : "s"} you added after the original evidence plan.`}
                </p>
              ) : null}

              {hasHiddenDetails ? (
                <div className="border-t bg-background/60 px-4 py-3">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-expanded={showAllDetails}
                    onClick={() => setShowAllDetails((value) => !value)}
                  >
                    {showAllDetails ? "Show concise evidence" : "Show full evidence details"}
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
