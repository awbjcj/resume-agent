import { useState } from "react";
import { AlertTriangleIcon, CheckCircle2Icon, CircleHelpIcon, RouteIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { MatchGap } from "./use-match-gap";
import { useCorrectRequirementTermType } from "./use-taxonomy";

const LAYER_LABELS = {
  career_core: "Career core",
  foundational: "Foundational",
  transferable_function: "Transferable functions",
  domain_industry: "Domains & industries",
  occupation_role: "Occupations & roles",
  enabler: "Tools, languages & credentials",
} as const;

const STATUS_LABELS = {
  verified_exact: "Verified exact",
  verified_equivalent: "Verified equivalent",
  covered_broader: "Covered, broader",
  covered_narrower: "Covered, narrower",
  transferable: "Transferable",
  partial: "Partial",
  level_gap: "Level gap",
  context_gap: "Context gap",
  recency_gap: "Recency gap",
  evidence_gap: "Evidence gap",
  tool_gap: "Tool gap",
  credential_gap: "Credential gap",
  unknown: "Unknown",
  absent: "Absent",
} as const;

type MatchResult = NonNullable<MatchGap["matchResults"]>[number];
type TypedRequirement = NonNullable<MatchGap["typedRequirements"]>[number];

const CORRECTABLE_TERM_TYPES = [
  "competency_family",
  "capability",
  "skill",
  "knowledge",
  "work_activity",
  "task",
  "method",
  "standard",
  "tool_technology",
  "artifact",
  "work_style",
  "language",
  "occupation_role",
  "industry_domain",
  "knowledge_domain",
  "credential",
  "requirement",
  "work_context",
  "learning_outcome",
] as const;

function statusTone(status: MatchResult["v2"]["status"]) {
  if (status.startsWith("verified_") || status.startsWith("covered_")) return "text-ready";
  if (status === "transferable" || status === "partial") return "text-warning-foreground";
  if (status === "unknown") return "text-muted-foreground";
  return "text-destructive";
}

function statusIcon(status: MatchResult["v2"]["status"]) {
  if (status.startsWith("verified_") || status.startsWith("covered_")) {
    return <CheckCircle2Icon aria-hidden="true" />;
  }
  if (status === "transferable" || status === "partial") return <RouteIcon aria-hidden="true" />;
  if (status === "unknown") return <CircleHelpIcon aria-hidden="true" />;
  return <AlertTriangleIcon aria-hidden="true" />;
}

function revisionNote(data: MatchGap) {
  return [data.matchingPolicyRevision, data.profileFactsRevision, data.assertionPolicyRevision]
    .filter(Boolean)
    .join(" · ");
}

function RequirementTypeCorrection({ requirement }: { requirement: TypedRequirement }) {
  const mutation = useCorrectRequirementTermType();
  const [newType, setNewType] = useState<(typeof CORRECTABLE_TERM_TYPES)[number]>("capability");
  const [rationale, setRationale] = useState("");
  const jobId = Number(requirement.jobId);
  const canSubmit = Number.isInteger(jobId) && rationale.trim().length > 0 && !mutation.isPending;

  return (
    <form
      className="mt-3 space-y-2 rounded-md border bg-background p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        mutation.mutate({
          jobId,
          requirementId: requirement.id,
          body: { newType, rationale: rationale.trim(), evidenceRefs: [] },
        });
      }}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Resolve unknown type</p>
      <label className="block text-sm font-medium" htmlFor={`requirement-type-${requirement.id}`}>
        Correct requirement type
      </label>
      <select
        id={`requirement-type-${requirement.id}`}
        className="h-9 w-full rounded-md border bg-background px-3 text-sm"
        value={newType}
        onChange={(event) => setNewType(event.target.value as typeof newType)}
      >
        {CORRECTABLE_TERM_TYPES.map((type) => (
          <option key={type} value={type}>{type.replaceAll("_", " ")}</option>
        ))}
      </select>
      <label className="block text-sm font-medium" htmlFor={`requirement-rationale-${requirement.id}`}>
        Correction rationale
      </label>
      <textarea
        id={`requirement-rationale-${requirement.id}`}
        className="min-h-20 w-full rounded-md border bg-background px-3 py-2 text-sm"
        maxLength={1000}
        required
        value={rationale}
        onChange={(event) => setRationale(event.target.value)}
      />
      <Button type="submit" size="sm" disabled={!canSubmit}>Save type correction</Button>
    </form>
  );
}

export function UccmMatrixPanel({ data }: { data: MatchGap }) {
  const state = data.uccmState ?? "disabled";
  if (state !== "ready") {
    if (state === "disabled") return null;
    const stale = state === "stale";
    return (
      <Alert role="status" variant={stale ? "destructive" : "default"}>
        <AlertTriangleIcon aria-hidden="true" />
        <AlertTitle>{stale ? "Capability analysis is stale" : "Capability analysis unavailable"}</AlertTitle>
        <AlertDescription>
          Legacy match-gap results remain available. UCCM results are hidden until coherent artifacts can be rebuilt.
          {data.uccmErrorCode && <span className="mt-1 block font-mono text-xs">{data.uccmErrorCode}</span>}
        </AlertDescription>
      </Alert>
    );
  }

  const requirements = new Map((data.typedRequirements ?? []).map((item) => [item.id, item]));
  const jobs = new Map(data.jobs.map((job) => [String(job.id), job]));
  const shadowMode = data.taxonomyManifest?.capabilityEffectiveMode === "shadow";

  return (
    <section aria-labelledby="uccm-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="uccm-heading" className="font-heading text-xl font-semibold">Career capability matrix</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Evidence-backed profile layers and source-grounded job requirements. Transfer and partial matches keep
            the candidate capability name visible; they are not treated as exact coverage.
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{revisionNote(data)}</span>
      </div>

      {shadowMode && (
        <Alert role="status" aria-label="Shadow analysis">
          <CircleHelpIcon aria-hidden="true" />
          <AlertTitle>Shadow analysis</AlertTitle>
          <AlertDescription>
            UCCM results are shown for comparison; legacy matching remains primary until reviewed activation gates pass.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {(data.profileProjection?.layers ?? []).map((layer) => (
          <Card key={layer.layer} size="sm">
            <CardHeader>
              <CardTitle>
                <h3>{LAYER_LABELS[layer.layer]}</h3>
              </CardTitle>
              <CardDescription>{layer.items.length} evidenced capabilities</CardDescription>
            </CardHeader>
            <CardContent>
              {layer.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">No supported claims yet</p>
              ) : (
                <ul className="space-y-2">
                  {layer.items.map((item) => (
                    <li key={`${layer.layer}-${item.conceptId}`} className="rounded-md border px-3 py-2">
                      <p className="font-medium">{item.display}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {item.conceptType.replaceAll("_", " ")} · {item.evidenceFactIds.length} evidence facts
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle><h3>Job requirements</h3></CardTitle>
          <CardDescription>
            Requirements stay separate from profile claims and retain their source text, strictness, and evidence.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {(data.matchResults ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No typed requirements are available for the current jobs.</p>
          ) : (
            <Accordion>
              {(data.matchResults ?? []).map((result) => {
                const requirement = requirements.get(result.v2.requirementId);
                const job = requirement ? jobs.get(requirement.jobId) : undefined;
                return (
                  <AccordionItem key={result.v2.id} value={result.v2.id}>
                    <AccordionTrigger className="gap-3 no-underline hover:no-underline">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{result.v2.requirementLabel}</span>
                        {result.v2.candidateLabel && result.v2.candidateLabel !== result.v2.requirementLabel && (
                          <p className="mt-1 text-xs font-normal text-muted-foreground">
                            Candidate capability: {result.v2.candidateLabel}
                          </p>
                        )}
                      </span>
                      <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                        <Badge variant="outline" className={cn("gap-1", statusTone(result.v2.status))}>
                          {statusIcon(result.v2.status)}
                          {STATUS_LABELS[result.v2.status]}
                        </Badge>
                        <span className="text-xs font-normal text-muted-foreground">
                          Legacy: {result.legacyCoverage}
                        </span>
                      </span>
                    </AccordionTrigger>
                    <AccordionContent className="grid gap-3 rounded-md bg-muted/40 p-3 sm:grid-cols-2">
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Job source</p>
                        <p className="mt-1">{requirement?.sourceText ?? "Source span unavailable"}</p>
                        {job && <p className="mt-1 text-xs text-muted-foreground">{job.company} · {job.title}</p>}
                        <p className="mt-2 text-xs text-muted-foreground">
                          {requirement?.requirementKind.replaceAll("_", " ")} · {requirement?.strictness.replaceAll("_", " ")}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Why this result</p>
                        {result.v2.candidateLabel && <p className="mt-1">{result.v2.candidateLabel}</p>}
                        <p className="mt-1 text-xs text-muted-foreground">
                          {result.v2.evidenceFactIds.length > 0
                            ? `Evidence: ${result.v2.evidenceFactIds.join(", ")}`
                            : "Evidence: none located"}
                        </p>
                        <p className="mt-2">{result.v2.recommendedAction}</p>
                        {requirement?.conceptType === "unknown" && (
                          <RequirementTypeCorrection requirement={requirement} />
                        )}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                );
              })}
            </Accordion>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
