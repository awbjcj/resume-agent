import { Fragment, useState } from "react";
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

const INITIAL_DOMAINS = 12;
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
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [domainLimit, setDomainLimit] = useState(INITIAL_DOMAINS);
  const [skillLimits, setSkillLimits] = useState<Record<string, number>>({});
  const maximum = Math.max(1, ...domainRows.map((domain) => domain.score));
  const visibleDomains = categoryRows.flatMap((category) => category.domains).slice(0, domainLimit);
  const categoryBySlug = new Map(categoryRows.map((category) => [category.slug, category]));

  return (
    <section aria-labelledby="ranked-domains-title" className="border-y bg-card">
      <header className="flex items-end justify-between gap-4 border-b px-4 py-4 sm:px-5">
        <div>
          <h2 id="ranked-domains-title" className="text-sm font-semibold">
            Ranked skill domains
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Expand a domain to inspect generalized skills and evidence status.
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {domainRows.length} domains
        </span>
      </header>

      <div className="divide-y">
        {visibleDomains.map((domain, index) => {
          const open = expanded.has(domain.id);
          const domainTarget = { kind: "domain" as const, key: domain.id, label: domain.label };
          const orderedSkills = sortSkillsWithin(domain.skills, (key) =>
            stateOf("skill", key),
          );
          const skillLimit = skillLimits[domain.id] ?? INITIAL_SKILLS;
          const category = categoryBySlug.get(domain.category);
          const showCategory = index === 0 || visibleDomains[index - 1].category !== domain.category;
          return (
            <Fragment key={domain.id}>
              {showCategory && category && (
                <div className="flex items-center gap-2 bg-muted/35 px-4 py-2 sm:px-5">
                  <span className="text-xs font-semibold uppercase tracking-wide">{category.label}</span>
                  <Badge variant={category.kind === "hard" ? "default" : "outline"}>
                    {category.kind}
                  </Badge>
                </div>
              )}
            <Collapsible
              key={domain.id}
              open={open}
              onOpenChange={(next) =>
                setExpanded((current) => {
                  const updated = new Set(current);
                  if (next) updated.add(domain.id);
                  else updated.delete(domain.id);
                  return updated;
                })
              }
            >
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 sm:px-5">
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
                    <span className="h-1.5 min-w-20 flex-1 overflow-hidden rounded-full bg-muted">
                      <span
                        className="block h-full rounded-full bg-primary"
                        style={{ width: `${(domain.score / maximum) * 100}%` }}
                      />
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {domain.score} · {domain.skillCount} skills · {domain.gapCount} gaps · {domain.adjacentCount} adjacent
                    </span>
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
                <ul className="border-t bg-muted/20 px-4 sm:px-5">
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
                  <div className="border-t px-5 py-2">
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
            </Fragment>
          );
        })}
      </div>

      {domainRows.length > domainLimit && (
        <div className="border-t px-5 py-3">
          <Button variant="outline" size="sm" onClick={() => setDomainLimit(domainLimit + 12)}>
            Show {Math.min(12, domainRows.length - domainLimit)} more domains
          </Button>
        </div>
      )}
    </section>
  );
}
