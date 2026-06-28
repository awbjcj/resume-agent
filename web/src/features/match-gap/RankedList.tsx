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
  UNTHEMED_ID,
  type SkillRow,
  type SuggestionState,
  type SuggestionTarget,
  type ThemeRow,
} from "./aggregate";

const INITIAL_THEMES = 12;
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
  themeRows,
  stateOf,
  selected,
  onToggleSelect,
  onOpenSkill,
}: {
  themeRows: ThemeRow[];
  stateOf: (kind: "skill" | "theme", key: string) => SuggestionState;
  selected: Set<string>;
  onToggleSelect: (target: SuggestionTarget) => void;
  onOpenSkill: (skill: SkillRow) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [themeLimit, setThemeLimit] = useState(INITIAL_THEMES);
  const [skillLimits, setSkillLimits] = useState<Record<string, number>>({});
  const maximum = Math.max(1, ...themeRows.map((theme) => theme.score));
  const visibleThemes = themeRows.slice(0, themeLimit);

  return (
    <section aria-labelledby="ranked-themes-title" className="border-y bg-card">
      <header className="flex items-end justify-between gap-4 border-b px-4 py-4 sm:px-5">
        <div>
          <h2 id="ranked-themes-title" className="text-sm font-semibold">
            Ranked skill themes
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Expand a theme to inspect generalized skills and evidence status.
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {themeRows.length} themes
        </span>
      </header>

      <div className="divide-y">
        {visibleThemes.map((theme) => {
          const open = expanded.has(theme.id);
          const themeTarget = { kind: "theme" as const, key: theme.id, label: theme.label };
          const orderedSkills = sortSkillsWithin(theme.skills, (key) =>
            stateOf("skill", key),
          );
          const skillLimit = skillLimits[theme.id] ?? INITIAL_SKILLS;
          return (
            <Collapsible
              key={theme.id}
              open={open}
              onOpenChange={(next) =>
                setExpanded((current) => {
                  const updated = new Set(current);
                  if (next) updated.add(theme.id);
                  else updated.delete(theme.id);
                  return updated;
                })
              }
            >
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 sm:px-5">
                <Checkbox
                  aria-label={`Select ${theme.label} theme`}
                  checked={selected.has(targetId(themeTarget))}
                  onCheckedChange={() => onToggleSelect(themeTarget)}
                  disabled={theme.id === UNTHEMED_ID}
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold">{theme.label}</span>
                    <StatusBadge state={stateOf("theme", theme.id)} />
                  </div>
                  <div className="mt-1.5 flex items-center gap-3">
                    <span className="h-1.5 min-w-20 flex-1 overflow-hidden rounded-full bg-muted">
                      <span
                        className="block h-full rounded-full bg-primary"
                        style={{ width: `${(theme.score / maximum) * 100}%` }}
                      />
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {theme.score} · {theme.skillCount} skills · {theme.gapCount} gaps
                    </span>
                  </div>
                </div>
                <CollapsibleTrigger
                  render={<Button variant="ghost" size="sm" />}
                  aria-label={`${open ? "Collapse" : "Expand"} ${theme.label}`}
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
                            <Badge variant={skill.covered ? "secondary" : "destructive"}>
                              {skill.covered ? "Covered" : "Gap"}
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
                          [theme.id]: skillLimit + INITIAL_SKILLS,
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
      </div>

      {themeRows.length > themeLimit && (
        <div className="border-t px-5 py-3">
          <Button variant="outline" size="sm" onClick={() => setThemeLimit(themeLimit + 12)}>
            Show {Math.min(12, themeRows.length - themeLimit)} more themes
          </Button>
        </div>
      )}
    </section>
  );
}
