import { useId, useState } from "react";
import { AlertTriangle, ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { components } from "@/lib/api/schema";
import { useEvidencePortfolio } from "./use-evidence-portfolio";

type Requirement = components["schemas"]["PortfolioRequirementOut"];

function coverageVariant(coverage: Requirement["coverage"]) {
  if (coverage === "covered") return "secondary" as const;
  if (coverage === "gap") return "destructive" as const;
  return "outline" as const;
}

export function EvidencePortfolioDisclosure({
  versionId,
  available,
}: {
  versionId: number;
  available: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const portfolio = useEvidencePortfolio(versionId, available && expanded);

  if (!available) return null;

  const data = portfolio.data;
  const excerpts = new Map(
    (data?.evidenceExcerpts ?? []).map((excerpt) => [excerpt.factId, excerpt]),
  );
  const omissions = data?.omissions ?? [];
  const outsideFactIds = data?.realizedOutsideFactIds ?? [];

  return (
    <div className="mt-3 border-t pt-3">
      <Button
        size="sm"
        variant="ghost"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <ChevronDown
          className={`size-4 transition-transform ${expanded ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
        Why this evidence?
      </Button>

      {expanded ? (
        <section
          id={panelId}
          aria-label="Evidence portfolio explanation"
          className="mt-3 rounded-lg border bg-muted/25 p-3 sm:p-4"
        >
          {portfolio.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Spinner data-icon="inline-start" />
              Loading evidence explanation
            </p>
          ) : null}
          {portfolio.isError ? (
            <p className="text-sm text-destructive" role="alert">
              Could not load the evidence explanation. {portfolio.error.message}
            </p>
          ) : null}
          {data ? (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">Evidence portfolio</h3>
                <Badge variant="outline">
                  {data.status === "deterministic_fallback"
                    ? "Deterministic fallback"
                    : data.status === "inherited"
                      ? "Inherited"
                      : "Planned"}
                </Badge>
                {(data.highlightTerms ?? []).map((term) => (
                  <Badge key={term} variant="secondary">{term}</Badge>
                ))}
              </div>

              {data.warning ? (
                <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-900 dark:text-amber-200" role="status">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  {data.warning}
                </p>
              ) : null}

              <div>
                <h4 className="font-medium">Ranked job requirements</h4>
                <ol className="mt-2 grid gap-2 lg:grid-cols-2">
                  {(data.requirements ?? []).map((requirement) => (
                    <li key={`${requirement.priority}-${requirement.text}`} className="rounded-md border bg-background p-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{requirement.priority}. {requirement.text}</span>
                        <Badge variant={coverageVariant(requirement.coverage)}>{requirement.coverage}</Badge>
                        {requirement.core ? <Badge>Core skill</Badge> : null}
                      </div>
                      {requirement.rationale ? (
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">{requirement.rationale}</p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </div>

              <div>
                <h4 className="font-medium">Selected evidence</h4>
                <ol className="mt-2 space-y-2">
                  {(data.selections ?? []).map((selection) => {
                    const selectedExcerpts = (selection.selectedFactIds ?? [])
                      .map((factId) => excerpts.get(factId))
                      .filter((excerpt) => excerpt !== undefined);
                    return (
                      <li key={selection.ownerId} className="rounded-md border bg-background p-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{selection.rank}. {selection.ownerKind}</span>
                          <Badge variant="outline">up to {selection.bulletBudget} bullets</Badge>
                          {selection.bridge ? <Badge variant="secondary">Bridge role</Badge> : null}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">{selection.rationale}</p>
                        {selectedExcerpts.length ? (
                          <ul className="mt-2 list-disc space-y-1 pl-5">
                            {selectedExcerpts.map((excerpt) => (
                              <li key={excerpt.factId}>{excerpt.text}</li>
                            ))}
                          </ul>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </div>

              {omissions.length ? (
                <div>
                  <h4 className="font-medium">Why other evidence was omitted</h4>
                  <ul className="mt-2 space-y-1 text-xs leading-5 text-muted-foreground">
                    {omissions.map((omission) => (
                      <li key={omission.ownerId}>{omission.ownerKind}: {omission.rationale}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {outsideFactIds.length ? (
                <p className="rounded-md border bg-background p-2 text-xs text-muted-foreground">
                  This revision also contains {outsideFactIds.length} user-added profile fact{outsideFactIds.length === 1 ? "" : "s"} outside the inherited portfolio.
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
