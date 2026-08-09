import { useState } from "react";
import { ChevronRightIcon, ExternalLinkIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import {
  sortSkillsWithin,
  targetId,
  UNASSIGNED_ID,
  type SkillRow,
  type SuggestionState,
  type SuggestionTarget,
  type DomainRow,
  type CategoryRow,
} from "./aggregate";

const INITIAL_DOMAINS = 8;
const INITIAL_SKILLS = 8;

const STATUS_LABEL: Record<SuggestionState, string> = {
  none: "Not generated",
  ready: "Ready",
  stale: "Stale",
  queued: "Queued",
  researching: "Researching",
  failed: "Failed",
  cancelled: "Cancelled",
  not_found: "Unavailable",
};

function StatusBadge({ state }: { state: SuggestionState }) {
  if (state === "none") return null;
  const variant = state === "failed" || state === "not_found" ? "destructive" : "outline";
  return (
    <Badge variant={variant} className={cn(state === "ready" && "border-ready text-ready")}>
      {STATUS_LABEL[state]}
    </Badge>
  );
}

// A dense, scannable stat line reused by both category and domain headers. Each
// figure is only rendered when it carries signal (score/gaps/adjacent hidden at
// zero) so a clean domain doesn't read as a wall of "0 · 0 · 0".
function StatLine({
  score,
  skillCount,
  gapCount,
  adjacentCount,
}: {
  score: number;
  skillCount: number;
  gapCount: number;
  adjacentCount: number;
}) {
  const parts = [
    `${skillCount} ${skillCount === 1 ? "skill" : "skills"}`,
    score > 0 ? `score ${score}` : null,
    gapCount > 0 ? `${gapCount} gaps` : null,
    adjacentCount > 0 ? `${adjacentCount} adjacent` : null,
  ].filter(Boolean);
  return (
    <span className="font-mono text-xs tabular-nums text-muted-foreground">
      {parts.join(" · ")}
    </span>
  );
}

function ScoreBar({ score, maximum }: { score: number; maximum: number }) {
  return (
    <span className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-full bg-muted">
      <span
        className="block h-full rounded-full bg-primary"
        style={{ width: `${Math.min(100, (score / maximum) * 100)}%` }}
      />
    </span>
  );
}

export function RankedList({
  domainRows,
  categoryRows,
  stateOf,
  selected,
  onToggleSelect,
  onOpenSkill,
}: {
  domainRows: DomainRow[];
  categoryRows: CategoryRow[];
  stateOf: (kind: "skill" | "domain", key: string) => SuggestionState;
  selected: Set<string>;
  onToggleSelect: (target: SuggestionTarget) => void;
  onOpenSkill: (skill: SkillRow) => void;
}) {
  // Categories default-open so the full taxonomy is visible at a glance;
  // domains default-closed to keep the outline compact until drilled into.
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());
  const [domainLimits, setDomainLimits] = useState<Record<string, number>>({});
  const [skillLimits, setSkillLimits] = useState<Record<string, number>>({});
  const maximum = Math.max(1, ...domainRows.map((domain) => domain.score));

  const setCategoryOpen = (slug: string, open: boolean) =>
    setCollapsedCategories((current) => {
      const next = new Set(current);
      if (open) next.delete(slug);
      else next.add(slug);
      return next;
    });
  const setDomainOpen = (id: string, open: boolean) =>
    setExpandedDomains((current) => {
      const next = new Set(current);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <section aria-labelledby="ranked-domains-title" className="border-y bg-card">
      <header className="flex items-end justify-between gap-4 border-b px-4 py-4 sm:px-5">
        <div>
          <h2 id="ranked-domains-title" className="text-sm font-semibold">
            Skill outline
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Expand a category to see its domains, then a domain to inspect skills and evidence status.
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {categoryRows.length} {categoryRows.length === 1 ? "category" : "categories"} · {domainRows.length} domains
        </span>
      </header>

      <div className="divide-y">
        {categoryRows.map((category) => {
          const categoryOpen = !collapsedCategories.has(category.slug);
          const domainLimit = domainLimits[category.slug] ?? INITIAL_DOMAINS;
          const visibleDomains = category.domains.slice(0, domainLimit);
          return (
            <Collapsible
              key={category.slug}
              open={categoryOpen}
              onOpenChange={(open) => setCategoryOpen(category.slug, open)}
            >
              <CollapsibleTrigger
                render={<Button variant="ghost" size="lg" />}
                aria-label={`${categoryOpen ? "Collapse" : "Expand"} ${category.label}`}
                className="h-auto w-full justify-start gap-3 rounded-none bg-muted/40 px-4 py-3 text-left hover:bg-muted/60 sm:px-5"
              >
                <ChevronRightIcon
                  aria-hidden
                  className={cn("shrink-0 text-muted-foreground transition-transform", categoryOpen && "rotate-90")}
                />
                <span className="text-xs font-semibold uppercase tracking-wide">{category.label}</span>
                <Badge variant={category.kind === "hard" ? "default" : "outline"}>
                  {category.kind}
                </Badge>
                <span className="ml-auto">
                  <StatLine
                    score={category.score}
                    skillCount={category.skillCount}
                    gapCount={category.gapCount}
                    adjacentCount={category.adjacentCount}
                  />
                </span>
              </CollapsibleTrigger>

              <CollapsibleContent>
                <div className="divide-y border-t">
                  {visibleDomains.map((domain) => {
                    const open = expandedDomains.has(domain.id);
                    const domainTarget = { kind: "domain" as const, key: domain.id, label: domain.label };
                    const orderedSkills = sortSkillsWithin(domain.skills, (key) =>
                      stateOf("skill", key),
                    );
                    const skillLimit = skillLimits[domain.id] ?? INITIAL_SKILLS;
                    return (
                      <Collapsible
                        key={domain.id}
                        open={open}
                        onOpenChange={(next) => setDomainOpen(domain.id, next)}
                      >
                        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 pl-6 sm:px-5 sm:pl-8">
                          <Checkbox
                            aria-label={`Select ${domain.label} domain`}
                            checked={selected.has(targetId(domainTarget))}
                            onCheckedChange={() => onToggleSelect(domainTarget)}
                            disabled={domain.id === UNASSIGNED_ID}
                          />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="truncate text-sm font-semibold">{domain.label}</span>
                              <StatusBadge state={stateOf("domain", domain.id)} />
                            </div>
                            <div className="mt-1.5 flex items-center gap-3">
                              <ScoreBar score={domain.score} maximum={maximum} />
                              <StatLine
                                score={domain.score}
                                skillCount={domain.skillCount}
                                gapCount={domain.gapCount}
                                adjacentCount={domain.adjacentCount}
                              />
                            </div>
                          </div>
                          <CollapsibleTrigger
                            render={<Button variant="ghost" size="sm" />}
                            aria-label={`${open ? "Collapse" : "Expand"} ${domain.label}`}
                          >
                            <ChevronRightIcon
                              data-icon="inline-end"
                              className={cn("transition-transform", open && "rotate-90")}
                            />
                          </CollapsibleTrigger>
                        </div>

                        <CollapsibleContent>
                          <ul className="border-t bg-muted/20 px-4 pl-6 sm:px-5 sm:pl-8">
                            {orderedSkills.slice(0, skillLimit).map((skill) => {
                              const skillTarget = {
                                kind: "skill" as const,
                                key: skill.key,
                                label: skill.skill,
                              };
                              return (
                                <li
                                  key={skill.key}
                                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b py-3 last:border-b-0"
                                >
                                  <Checkbox
                                    aria-label={`Select ${skill.skill}`}
                                    checked={selected.has(targetId(skillTarget))}
                                    onCheckedChange={() => onToggleSelect(skillTarget)}
                                  />
                                  <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className="truncate text-sm font-medium">{skill.skill}</span>
                                      <Badge
                                        variant={
                                          skill.coverage === "covered"
                                            ? "secondary"
                                            : skill.coverage === "gap"
                                              ? "destructive"
                                              : "outline"
                                        }
                                        className={cn(
                                          skill.coverage === "adjacent" &&
                                            "border-adjacent text-adjacent",
                                        )}
                                      >
                                        {skill.coverage === "covered"
                                          ? "Covered"
                                          : skill.coverage === "adjacent"
                                            ? "Adjacent"
                                            : "Gap"}
                                      </Badge>
                                      <StatusBadge state={stateOf("skill", skill.key)} />
                                    </div>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                      {skill.jobCount} {skill.jobCount === 1 ? "job" : "jobs"} · score {skill.score}
                                    </p>
                                    {skill.domainId === null && skill.groupingStatus && (
                                      <p className="mt-1 text-xs text-muted-foreground">
                                        Grouping {skill.groupingStatus.state}: {skill.groupingStatus.reason}
                                      </p>
                                    )}
                                  </div>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    aria-label={`Open ${skill.skill} details`}
                                    onClick={() => onOpenSkill(skill)}
                                  >
                                    Details
                                    <ExternalLinkIcon data-icon="inline-end" />
                                  </Button>
                                </li>
                              );
                            })}
                          </ul>
                          {orderedSkills.length > skillLimit && (
                            <div className="border-t px-5 py-2 pl-6 sm:pl-8">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() =>
                                  setSkillLimits((limits) => ({
                                    ...limits,
                                    [domain.id]: skillLimit + INITIAL_SKILLS,
                                  }))
                                }
                              >
                                Show {Math.min(INITIAL_SKILLS, orderedSkills.length - skillLimit)} more skills
                              </Button>
                            </div>
                          )}
                        </CollapsibleContent>
                      </Collapsible>
                    );
                  })}
                  {category.domains.length > domainLimit && (
                    <div className="px-5 py-2 pl-6 sm:pl-8">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setDomainLimits((limits) => ({
                            ...limits,
                            [category.slug]: domainLimit + INITIAL_DOMAINS,
                          }))
                        }
                      >
                        Show {Math.min(INITIAL_DOMAINS, category.domains.length - domainLimit)} more domains
                      </Button>
                    </div>
                  )}
                </div>
              </CollapsibleContent>
            </Collapsible>
          );
        })}
      </div>
    </section>
  );
}
