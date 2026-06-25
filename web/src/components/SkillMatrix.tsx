// Full skill set, grouped Must-have / Nice-to-have. Two independent channels:
//   required  -> which group (must vs nice)
//   covered   -> chip fill (solid = you have it, dashed outline = gap)
// Staggered rise-in on open. Used by the job detail modal rail.

import type { SkillTag } from "@/lib/filters/types";

function Chip({
  tag,
  active,
  index,
}: {
  tag: SkillTag;
  active: boolean;
  index: number;
}) {
  return (
    <span
      className="skill-chip rise-in"
      data-covered={tag.covered}
      data-active={active}
      style={{ "--rise-i": index } as React.CSSProperties}
      title={
        tag.covered ? "Covered by your profile" : "Gap — not in your profile yet"
      }
    >
      <span aria-hidden className="text-[0.7em] opacity-80">
        {tag.covered ? "●" : "○"}
      </span>
      {tag.name}
    </span>
  );
}

function Group({
  label,
  tags,
  activeSkills,
  baseIndex,
}: {
  label: string;
  tags: SkillTag[];
  activeSkills: Set<string>;
  baseIndex: number;
}) {
  if (tags.length === 0) return null;
  return (
    <div>
      <div className="mb-2.5 flex items-baseline gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {label}
        </h4>
        <span className="text-xs font-medium tabular-nums text-muted-foreground/70">
          {tags.length}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {tags.map((t, i) => (
          <Chip
            key={t.name}
            tag={t}
            active={activeSkills.has(t.name.toLowerCase())}
            index={baseIndex + i}
          />
        ))}
      </div>
    </div>
  );
}

export function SkillMatrix({
  skills,
  activeSkills = new Set(),
}: {
  skills: SkillTag[];
  activeSkills?: Set<string>;
}) {
  const must = skills.filter((s) => s.required);
  const best = skills.filter((s) => !s.required);
  const covered = skills.filter((s) => s.covered).length;

  if (skills.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No skills extracted for this job.</p>
    );
  }

  return (
    <div className="space-y-4">
      <Group label="Must-have" tags={must} activeSkills={activeSkills} baseIndex={0} />
      <Group
        label="Nice-to-have"
        tags={best}
        activeSkills={activeSkills}
        baseIndex={must.length}
      />
      <div className="flex items-center gap-4 border-t pt-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="text-primary">●</span> you have
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden>○</span> gap
        </span>
        <span className="ml-auto font-medium tabular-nums">
          {covered}/{skills.length} covered
        </span>
      </div>
    </div>
  );
}
