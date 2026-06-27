import type { components } from "@/lib/api/schema";

type Payload = components["schemas"]["MatchGapOut"];
type JobLite = Payload["jobs"][number];
type Edge = Payload["edges"][number];

export const SOURCE_WEIGHT = { must: 3, nice: 2, tech: 1 } as const;

export interface Filters {
  company: string | null;
  seniority: string | null;
  gapsOnly: boolean;
  weighting: "essential" | "popular";
}

export interface SkillRow {
  skill: string;
  themeId: string | null;
  covered: boolean;
  score: number;
  jobCount: number;
  must: number;
  nice: number;
  tech: number;
}

export interface ThemeGroup {
  id: string;
  label: string;
  score: number;
  skills: SkillRow[];
}

export interface StatRow {
  key: string;
  topSkills: { skill: string; score: number }[];
  gapCount: number;
}

export interface DerivedView {
  skills: SkillRow[];
  themes: ThemeGroup[];
  byCompany: StatRow[];
  byPosition: StatRow[];
  jobsForSkill: (skill: string) => JobLite[];
  jobsForTheme: (themeId: string) => JobLite[];
  companies: string[];
  seniorities: string[];
}

function uniqueSorted(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

function summarize(
  edges: Edge[],
  coveredBySkill: Map<string, boolean>,
  themeBySkill: Map<string, string | null>,
  filters: Filters,
): SkillRow[] {
  type Counts = { must: number; nice: number; tech: number; jobs: Set<number> };
  const countsBySkill = new Map<string, Counts>();

  for (const edge of edges) {
    const counts = countsBySkill.get(edge.skill) ?? {
      must: 0,
      nice: 0,
      tech: 0,
      jobs: new Set<number>(),
    };
    counts[edge.source] += 1;
    counts.jobs.add(edge.jobId);
    countsBySkill.set(edge.skill, counts);
  }

  return [...countsBySkill.entries()]
    .map(([skill, counts]) => ({
      skill,
      themeId: themeBySkill.get(skill) ?? null,
      covered: coveredBySkill.get(skill) ?? false,
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
    }))
    .filter((row) => !filters.gapsOnly || !row.covered)
    .sort((left, right) => right.score - left.score || left.skill.localeCompare(right.skill));
}

export function deriveView(payload: Payload, filters: Filters): DerivedView {
  const jobById = new Map(payload.jobs.map((job) => [job.id, job]));
  const coveredBySkill = new Map(payload.skills.map((skill) => [skill.skill, skill.covered]));
  const themeBySkill = new Map(payload.skills.map((skill) => [skill.skill, skill.themeId]));
  const labelByTheme = new Map(payload.themes.map((theme) => [theme.id, theme.label]));

  const edges = payload.edges.filter((edge) => {
    const job = jobById.get(edge.jobId);
    if (!job) return false;
    if (filters.company && job.company !== filters.company) return false;
    if (filters.seniority && job.seniority !== filters.seniority) return false;
    return true;
  });
  const skills = summarize(edges, coveredBySkill, themeBySkill, filters);

  const themeGroups = new Map<string, ThemeGroup>();
  for (const skill of skills) {
    const id = skill.themeId ?? "__none__";
    const label = skill.themeId ? (labelByTheme.get(skill.themeId) ?? skill.themeId) : "Unthemed";
    const group = themeGroups.get(id) ?? { id, label, score: 0, skills: [] };
    group.skills.push(skill);
    group.score += skill.score;
    themeGroups.set(id, group);
  }
  const themes = [...themeGroups.values()].sort(
    (left, right) => right.score - left.score || left.label.localeCompare(right.label),
  );

  const jobIdsBySkill = new Map<string, Set<number>>();
  for (const edge of edges) {
    const jobIds = jobIdsBySkill.get(edge.skill) ?? new Set<number>();
    jobIds.add(edge.jobId);
    jobIdsBySkill.set(edge.skill, jobIds);
  }

  const jobsForSkill = (skill: string): JobLite[] =>
    [...(jobIdsBySkill.get(skill) ?? new Set<number>())]
      .map((id) => jobById.get(id))
      .filter((job): job is JobLite => Boolean(job));

  const jobsForTheme = (themeId: string): JobLite[] => {
    const members = new Set(
      payload.skills.filter((skill) => skill.themeId === themeId).map((skill) => skill.skill),
    );
    const jobIds = new Set(
      edges.filter((edge) => members.has(edge.skill)).map((edge) => edge.jobId),
    );
    return [...jobIds]
      .map((id) => jobById.get(id))
      .filter((job): job is JobLite => Boolean(job));
  };

  const rollup = (facet: (job: JobLite) => string | null | undefined): StatRow[] => {
    const edgesByKey = new Map<string, Edge[]>();
    for (const edge of edges) {
      const job = jobById.get(edge.jobId);
      if (!job) continue;
      const key = facet(job);
      if (!key) continue;
      const facetEdges = edgesByKey.get(key) ?? [];
      facetEdges.push(edge);
      edgesByKey.set(key, facetEdges);
    }

    return [...edgesByKey.entries()]
      .map(([key, facetEdges]) => {
        const rows = summarize(facetEdges, coveredBySkill, themeBySkill, filters);
        return {
          key,
          topSkills: rows.slice(0, 5).map((row) => ({ skill: row.skill, score: row.score })),
          gapCount: rows.filter((row) => !row.covered).length,
        };
      })
      .sort((left, right) => left.key.localeCompare(right.key));
  };

  return {
    skills,
    themes,
    byCompany: rollup((job) => job.company),
    byPosition: rollup((job) => job.title),
    jobsForSkill,
    jobsForTheme,
    companies: uniqueSorted(payload.jobs.map((job) => job.company)),
    seniorities: uniqueSorted(payload.jobs.map((job) => job.seniority)),
  };
}
