import type { SkillRow } from "./aggregate";

function sizeClass(score: number, maximum: number): string {
  const ratio = maximum > 0 ? score / maximum : 0;
  if (ratio > 0.8) return "text-3xl";
  if (ratio > 0.6) return "text-2xl";
  if (ratio > 0.4) return "text-xl";
  if (ratio > 0.2) return "text-lg";
  return "text-sm";
}

export function WordCloud({
  skills,
  onSelect,
}: {
  skills: SkillRow[];
  onSelect: (skill: string) => void;
}) {
  const maximum = skills.reduce((current, skill) => Math.max(current, skill.score), 0);

  return (
    <section aria-labelledby="skill-cloud-title" className="border-y bg-card/65 px-5 py-6">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h2 id="skill-cloud-title" className="text-sm font-semibold">
            Demand landscape
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Scale reflects weighted demand. Dashed labels mark gaps.
          </p>
        </div>
      </div>
      <div className="flex min-h-44 flex-wrap content-center items-center justify-center gap-x-5 gap-y-3">
        {skills.map((skill) => (
          <button
            key={skill.skill}
            type="button"
            data-covered={skill.covered}
            onClick={() => onSelect(skill.skill)}
            aria-label={`${skill.skill}, ${skill.covered ? "covered" : "gap"}, score ${skill.score}, ${skill.jobCount} jobs`}
            title={`${skill.skill} · score ${skill.score} · ${skill.jobCount} jobs`}
            className={`${sizeClass(skill.score, maximum)} rounded-sm border-b px-1 py-0.5 font-semibold leading-tight transition-colors motion-reduce:transition-none ${
              skill.covered
                ? "border-transparent text-muted-foreground hover:text-foreground"
                : "border-dashed border-primary/60 text-primary hover:border-primary hover:text-primary/80"
            }`}
          >
            {skill.skill}
          </button>
        ))}
      </div>
    </section>
  );
}
