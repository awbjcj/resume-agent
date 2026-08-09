import { BriefcaseBusinessIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { SkillRow, SuggestionState } from "./aggregate";
import { SuggestionPanel } from "./SuggestionPanel";
import { useGenerateSuggestion, useSuggestion } from "./use-suggestion";

type Job = {
  id: number;
  company?: string | null;
  title?: string | null;
  seniority?: string | null;
};

function stateLabel(state: SuggestionState): string {
  if (state === "none") return "Not generated";
  if (state === "not_found") return "Unavailable";
  return state[0].toUpperCase() + state.slice(1);
}

export function SkillModal({
  skill,
  domainLabel,
  state,
  jobs,
  onClose,
}: {
  skill: SkillRow | null;
  domainLabel: string | null;
  state: SuggestionState;
  jobs: Job[];
  onClose: () => void;
}) {
  const open = skill !== null;
  const { data: envelope, isLoading, isError, refetch } = useSuggestion(
    "skill",
    skill?.key ?? null,
    open,
  );
  const { generate, generating } = useGenerateSuggestion();
  const members = Object.entries(skill?.members ?? {}).sort(
    ([left, leftCount], [right, rightCount]) =>
      rightCount - leftCount || left.localeCompare(right),
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="block max-h-[92vh] max-w-[calc(100%-1.5rem)] overflow-hidden p-0 sm:max-w-6xl">
        {skill && (
          <div className="flex max-h-[92vh] flex-col">
            <DialogHeader className="border-b bg-accent/35 px-6 py-5 pr-14 sm:px-8 sm:py-6">
              <div className="flex flex-wrap items-center gap-2">
                {domainLabel && <Badge variant="outline">{domainLabel}</Badge>}
                <Badge
                  variant={
                    skill.coverage === "covered"
                      ? "secondary"
                      : skill.coverage === "gap"
                        ? "destructive"
                        : "outline"
                  }
                  className={
                    skill.coverage === "adjacent" ? "border-adjacent text-adjacent" : undefined
                  }
                >
                  {skill.coverage === "covered"
                    ? "Covered"
                    : skill.coverage === "adjacent"
                      ? "Adjacent"
                      : "Gap"}
                </Badge>
                <Badge variant="outline">{stateLabel(state)}</Badge>
              </div>
              <DialogTitle className="text-2xl font-semibold sm:text-3xl">
                {skill.skill}
              </DialogTitle>
              <DialogDescription>
                {skill.jobCount} target {skill.jobCount === 1 ? "job" : "jobs"} · demand score {skill.score}
              </DialogDescription>
              {skill.domainId === null && skill.groupingStatus && (
                <p role="status" className="mt-2 text-sm text-muted-foreground">
                  Grouping {skill.groupingStatus.state}: {skill.groupingStatus.reason}
                </p>
              )}
            </DialogHeader>

            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              <aside className="shrink-0 overflow-y-auto border-b bg-muted/25 p-5 lg:w-80 lg:border-r lg:border-b-0">
                <section aria-labelledby="skill-phrasing-title">
                  <h2 id="skill-phrasing-title" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Phrasings in job descriptions
                  </h2>
                  <ul className="mt-3 divide-y border-y">
                    {members.map(([member, count]) => (
                      <li key={member} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                        <span>{member}</span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {count} {count === 1 ? "job" : "jobs"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>

                <section aria-labelledby="source-mix-title" className="mt-6">
                  <h2 id="source-mix-title" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Source mix
                  </h2>
                  <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                    {[
                      ["Must", skill.must],
                      ["Nice", skill.nice],
                      ["Tech", skill.tech],
                    ].map(([label, count]) => (
                      <div key={label} className="border bg-background px-2 py-3">
                        <dt className="text-xs text-muted-foreground">{label}</dt>
                        <dd className="mt-1 font-mono text-lg font-semibold">{count}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              </aside>

              <section className="min-h-0 min-w-0 flex-1 overflow-y-auto p-5 sm:p-6">
                <Tabs defaultValue="suggestion">
                  <TabsList>
                    <TabsTrigger value="suggestion">Suggestion</TabsTrigger>
                    <TabsTrigger value="roles">Roles ({jobs.length})</TabsTrigger>
                  </TabsList>
                  <TabsContent value="suggestion" className="mt-5">
                    <SuggestionPanel
                      envelope={envelope}
                      isLoading={isLoading}
                      isError={isError}
                      onRetry={() => void refetch()}
                      onGenerate={() => void generate("skill", skill.key)}
                      generating={generating}
                    />
                  </TabsContent>
                  <TabsContent value="roles" className="mt-5">
                    {jobs.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No target roles match the current filters.</p>
                    ) : (
                      <ul className="divide-y border-y">
                        {jobs.map((job) => (
                          <li key={job.id} className="flex gap-3 py-3">
                            <BriefcaseBusinessIcon className="mt-0.5 size-4 shrink-0 text-primary" />
                            <div>
                              <p className="text-sm font-medium">{job.company ?? "Unknown company"}</p>
                              <p className="mt-0.5 text-sm text-muted-foreground">
                                {job.title ?? "Untitled role"}
                                {job.seniority ? ` · ${job.seniority}` : ""}
                              </p>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </TabsContent>
                </Tabs>
              </section>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
