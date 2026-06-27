import { AlertTriangle, Check } from "lucide-react";

import type { SkillRow } from "./aggregate";

export function RankedList({
  skills,
  onSelect,
}: {
  skills: SkillRow[];
  onSelect: (skill: string) => void;
}) {
  const maximum = skills.reduce((current, skill) => Math.max(current, skill.score), 0) || 1;

  return (
    <section aria-labelledby="ranked-skills-title" className="border-y bg-card">
      <div className="flex items-end justify-between gap-4 border-b px-5 py-4">
        <div>
          <h2 id="ranked-skills-title" className="text-sm font-semibold">
            Ranked demand
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Open a skill to inspect the target roles behind its score.
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{skills.length} skills</span>
      </div>
      <ol className="divide-y">
        {skills.map((skill, index) => (
          <li key={skill.skill}>
            <button
              type="button"
              onClick={() => onSelect(skill.skill)}
              aria-label={`${skill.skill}, ${skill.covered ? "covered" : "gap"}, score ${skill.score}`}
              className="grid w-full grid-cols-[2rem_minmax(8rem,1fr)_minmax(5rem,1.5fr)_3rem] items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-accent/55 motion-reduce:transition-none"
            >
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{skill.skill}</span>
                <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                  {skill.covered ? <Check className="size-3" /> : <AlertTriangle className="size-3" />}
                  {skill.covered ? "Covered" : "Gap"} · {skill.jobCount} jobs
                </span>
              </span>
              <span className="h-1.5 overflow-hidden rounded-full bg-muted">
                <span
                  className={`block h-full rounded-full ${skill.covered ? "bg-muted-foreground/45" : "bg-primary"}`}
                  style={{ width: `${(skill.score / maximum) * 100}%` }}
                />
              </span>
              <span className="text-right font-mono text-sm font-semibold tabular-nums">
                {skill.score}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
