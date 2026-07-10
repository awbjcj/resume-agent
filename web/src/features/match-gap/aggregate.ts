import type { components } from "@/lib/api/schema";

type Payload = components["schemas"]["MatchGapOut"];
type JobLite = Payload["jobs"][number];
type SuggestionKind = "skill" | "theme";

export const SOURCE_WEIGHT = { must: 3, nice: 2, tech: 1 } as const;
export const UNTHEMED_ID = "__unthemed__";

export interface Filters {
  q: string;
  company: string | null;
  seniority: string | null;
  gapsOnly: boolean;
  weighting: "essential" | "popular";
}

export interface SuggestionTarget {
  kind: SuggestionKind;
  key: string;
  label?: string;
}

export type SuggestionState =
  | "none"
  | "ready"
  | "stale"
  | "queued"
  | "researching"
  | "failed"
  | "cancelled"
  | "not_found";

export interface SkillRow {
  key: string;
  skill: string;
  themeId: string | null;
  covered: boolean;
  coverage: "covered" | "adjacent" | "gap";
  score: number;
  jobCount: number;
  must: number;
  nice: number;
  tech: number;
  members: Record<string, number>;
}

export interface ThemeRow {
  id: string;
  label: string;
  score: number;
  jobCount: number;
  skillCount: number;
  gapCount: number;
  adjacentCount: number;
  skills: SkillRow[];
}

export interface DerivedView {
  skills: SkillRow[];
  themeRows: ThemeRow[];
  filteredJobCount: number;
  jobsForSkill: (key: string) => JobLite[];
  jobsForTheme: (themeId: string) => JobLite[];
  companies: string[];
  seniorities: string[];
  persistedStateOf: (kind: SuggestionKind, key: string) => "ready" | "stale" | undefined;
}

type Counts = {
  must: number;
  nice: number;
  tech: number;
  jobs: Set<number>;
};

function uniqueSorted(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

export function targetId(target: Pick<SuggestionTarget, "kind" | "key">): string {
  return JSON.stringify([target.kind, target.key]);
}

export function sortSkillsWithin(
  skills: SkillRow[],
  stateOf: (key: string) => SuggestionState,
): SkillRow[] {
  return [...skills].sort((left, right) => {
    const readyDifference =
      Number(stateOf(right.key) === "ready") - Number(stateOf(left.key) === "ready");
    return (
      readyDifference ||
      right.score - left.score ||
      left.skill.localeCompare(right.skill) ||
      left.key.localeCompare(right.key)
    );
  });
}

export function deriveView(payload: Payload, filters: Filters): DerivedView {
  const jobById = new Map(payload.jobs.map((job) => [job.id, job]));
  const filteredJobs = payload.jobs.filter(
    (job) =>
      (!filters.company || job.company === filters.company) &&
      (!filters.seniority || job.seniority === filters.seniority),
  );
  const filteredJobIds = new Set(filteredJobs.map((job) => job.id));
  const edges = payload.edges.filter((edge) => filteredJobIds.has(edge.jobId));

  const countsBySkill = new Map<string, Counts>();
  const jobsBySkill = new Map<string, Set<number>>();
  for (const edge of edges) {
    const counts = countsBySkill.get(edge.skillKey) ?? {
      must: 0,
      nice: 0,
      tech: 0,
      jobs: new Set<number>(),
    };
    counts[edge.source] += 1;
    counts.jobs.add(edge.jobId);
    countsBySkill.set(edge.skillKey, counts);
    jobsBySkill.set(edge.skillKey, counts.jobs);
  }

  const q = filters.q.trim().toLowerCase();
  const skills = payload.skills
    .flatMap((node): SkillRow[] => {
      const counts = countsBySkill.get(node.key);
      const coverage = node.coverage ?? (node.covered ? "covered" : "gap");
      if (!counts || (filters.gapsOnly && coverage !== "gap")) return [];
      if (q && !node.skill.toLowerCase().includes(q)) return [];
      return [
        {
          key: node.key,
          skill: node.skill,
          themeId: node.themeId ?? null,
          covered: node.covered,
          coverage,
          score:
            filters.weighting === "popular"
              ? counts.jobs.size
              : counts.must * SOURCE_WEIGHT.must +
                counts.nice * SOURCE_WEIGHT.nice +
                counts.tech * SOURCE_WEIGHT.tech,
          jobCount: counts.jobs.size,
          must: counts.must,
          nice: counts.nice,
          tech: counts.tech,
          members: node.members,
        },
      ];
    })
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.skill.localeCompare(right.skill) ||
        left.key.localeCompare(right.key),
    );

  const themeLabels = new Map(payload.themes.map((theme) => [theme.id, theme.label]));
  const themeGroups = new Map<string, ThemeRow & { jobs: Set<number> }>();
  for (const skill of skills) {
    const id = skill.themeId ?? UNTHEMED_ID;
    const group = themeGroups.get(id) ?? {
      id,
      label: id === UNTHEMED_ID ? "Unthemed" : (themeLabels.get(id) ?? id),
      score: 0,
      jobCount: 0,
      skillCount: 0,
      gapCount: 0,
      adjacentCount: 0,
      skills: [],
      jobs: new Set<number>(),
    };
    group.score += skill.score;
    group.skillCount += 1;
    group.gapCount += Number(skill.coverage === "gap");
    group.adjacentCount += Number(skill.coverage === "adjacent");
    group.skills.push(skill);
    for (const jobId of jobsBySkill.get(skill.key) ?? []) group.jobs.add(jobId);
    group.jobCount = group.jobs.size;
    themeGroups.set(id, group);
  }
  const themeRows = [...themeGroups.values()]
    .map((theme) => ({
      id: theme.id,
      label: theme.label,
      score: theme.score,
      jobCount: theme.jobCount,
      skillCount: theme.skillCount,
      gapCount: theme.gapCount,
      adjacentCount: theme.adjacentCount,
      skills: theme.skills,
    }))
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.label.localeCompare(right.label) ||
        left.id.localeCompare(right.id),
    );

  const jobsForSkill = (key: string): JobLite[] =>
    [...(jobsBySkill.get(key) ?? [])]
      .map((jobId) => jobById.get(jobId))
      .filter((job): job is JobLite => Boolean(job));

  const jobsForTheme = (themeId: string): JobLite[] => {
    const jobIds = new Set<number>();
    for (const skill of skills) {
      if ((skill.themeId ?? UNTHEMED_ID) !== themeId) continue;
      for (const jobId of jobsBySkill.get(skill.key) ?? []) jobIds.add(jobId);
    }
    return [...jobIds]
      .map((jobId) => jobById.get(jobId))
      .filter((job): job is JobLite => Boolean(job));
  };

  const persistedStatus = new Map(
    (payload.suggestionStatuses ?? []).map((status) => [
      targetId({ kind: status.kind, key: status.key }),
      status.state,
    ]),
  );

  return {
    skills,
    themeRows,
    filteredJobCount: filteredJobs.length,
    jobsForSkill,
    jobsForTheme,
    companies: uniqueSorted(payload.jobs.map((job) => job.company)),
    seniorities: uniqueSorted(payload.jobs.map((job) => job.seniority)),
    persistedStateOf: (kind, key) => persistedStatus.get(targetId({ kind, key })),
  };
}
