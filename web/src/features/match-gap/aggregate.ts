import type { components } from "@/lib/api/schema";

type Payload = components["schemas"]["MatchGapOut"];
type JobLite = Payload["jobs"][number];
type SuggestionKind = "skill" | "domain";

export const SOURCE_WEIGHT = { must: 3, nice: 2, tech: 1 } as const;
export const UNASSIGNED_ID = "__unassigned__";

// Mirrors tracking/match_gap.py's TARGET_STATUSES -- every status a job in
// this payload can have, ordered most- to least-progressed like
// features/pipeline/pipeline-stages.ts's PIPELINE_STAGE_ORDER.
export const TARGET_STATUSES = ["tailored", "rendered", "approved", "shortlisted"] as const;

export function defaultTargetStatuses(): Set<string> {
  return new Set(TARGET_STATUSES);
}

export interface Filters {
  q: string;
  company: string | null;
  seniority: string | null;
  statuses: Set<string>;
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
  domainId: string | null;
  covered: boolean;
  coverage: "covered" | "adjacent" | "gap";
  score: number;
  jobCount: number;
  must: number;
  nice: number;
  tech: number;
  members: Record<string, number>;
  groupingStatus?: {
    state: "uncertain" | "failed";
    reason: string;
    lastAttemptedAt: string;
  } | null;
}

/**
 * Weighting changes rank only; every other filter changes which skill keys are
 * visible and therefore becomes the server-side regroup scope.
 */
export function hasActiveScopeFilters(filters: Filters): boolean {
  const configuredTargets = new Set<string>(TARGET_STATUSES);
  return (
    Boolean(filters.q.trim()) ||
    filters.company !== null ||
    filters.seniority !== null ||
    filters.gapsOnly ||
    TARGET_STATUSES.some((status) => !filters.statuses.has(status)) ||
    [...filters.statuses].some((status) => !configuredTargets.has(status))
  );
}

export function visibleUnassignedSkillKeys(view: Pick<DerivedView, "skills">): string[] {
  return view.skills
    .filter((skill) => skill.domainId === null)
    .map((skill) => skill.key)
    .sort();
}

export interface DomainRow {
  id: string;
  label: string;
  category: string;
  score: number;
  jobCount: number;
  skillCount: number;
  gapCount: number;
  adjacentCount: number;
  skills: SkillRow[];
}

export interface CategoryRow {
  slug: string;
  label: string;
  kind: "hard" | "soft";
  score: number;
  jobCount: number;
  skillCount: number;
  gapCount: number;
  adjacentCount: number;
  domains: DomainRow[];
}

export interface DerivedView {
  skills: SkillRow[];
  domainRows: DomainRow[];
  categoryRows: CategoryRow[];
  filteredJobCount: number;
  jobsForSkill: (key: string) => JobLite[];
  jobsForDomain: (domainId: string) => JobLite[];
  companies: string[];
  seniorities: string[];
  statusCounts: Record<string, number>;
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
  // Leave-one-out, mirroring the board facet convention: counts reflect every
  // other active filter but not the stage filter itself, so its own popover
  // options never vanish as you toggle them.
  const jobsBeforeStatus = payload.jobs.filter(
    (job) =>
      (!filters.company || job.company === filters.company) &&
      (!filters.seniority || job.seniority === filters.seniority),
  );
  const statusCounts: Record<string, number> = {};
  for (const job of jobsBeforeStatus) {
    statusCounts[job.status] = (statusCounts[job.status] ?? 0) + 1;
  }
  const filteredJobs = jobsBeforeStatus.filter((job) => filters.statuses.has(job.status));
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
      const observedCounts = countsBySkill.get(node.key);
      if (!observedCounts && node.jobCount > 0) return [];
      const counts = observedCounts ?? {
        must: 0,
        nice: 0,
        tech: 0,
        jobs: new Set<number>(),
      };
      const coverage = node.coverage ?? (node.covered ? "covered" : "gap");
      if (filters.gapsOnly && coverage !== "gap") return [];
      if (q && !node.skill.toLowerCase().includes(q)) return [];
      return [
        {
          key: node.key,
          skill: node.skill,
          domainId: node.domainId ?? null,
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
          groupingStatus: node.groupingStatus ?? null,
        },
      ];
    })
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.skill.localeCompare(right.skill) ||
        left.key.localeCompare(right.key),
    );

  const domainLabels = new Map(payload.domains.map((domain) => [domain.id, domain.label]));
  const domainCategory = new Map(payload.domains.map((domain) => [domain.id, domain.category]));
  const domainGroups = new Map<string, DomainRow & { jobs: Set<number> }>();
  for (const skill of skills) {
    const id = skill.domainId ?? UNASSIGNED_ID;
    const group = domainGroups.get(id) ?? {
      id,
      label: id === UNASSIGNED_ID ? "Unassigned" : (domainLabels.get(id) ?? id),
      category: id === UNASSIGNED_ID ? "other" : (domainCategory.get(id) ?? "other"),
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
    domainGroups.set(id, group);
  }
  const domainRows = [...domainGroups.values()]
    .map((domain) => ({
      id: domain.id,
      label: domain.label,
      category: domain.category,
      score: domain.score,
      jobCount: domain.jobCount,
      skillCount: domain.skillCount,
      gapCount: domain.gapCount,
      adjacentCount: domain.adjacentCount,
      skills: domain.skills,
    }))
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.label.localeCompare(right.label) ||
        left.id.localeCompare(right.id),
    );

  const categoryMeta = new Map(payload.categories.map((category) => [category.slug, category]));
  const domainsByCategory = new Map<string, DomainRow[]>();
  for (const domain of domainRows) {
    domainsByCategory.set(domain.category, [
      ...(domainsByCategory.get(domain.category) ?? []),
      domain,
    ]);
  }
  const orderedSlugs = [
    ...payload.categories.map((category) => category.slug),
    ...(domainsByCategory.has("other") && !categoryMeta.has("other") ? ["other"] : []),
  ];
  const categoryRows: CategoryRow[] = orderedSlugs.flatMap((slug) => {
    const domains = domainsByCategory.get(slug) ?? [];
    if (domains.length === 0) return [];
    const meta = categoryMeta.get(slug) ?? {
      slug,
      label: "Other",
      kind: "hard" as const,
    };
    const jobs = new Set<number>();
    for (const domain of domains) {
      for (const skill of domain.skills) {
        for (const jobId of jobsBySkill.get(skill.key) ?? []) jobs.add(jobId);
      }
    }
    return [{
      slug,
      label: meta.label,
      kind: meta.kind,
      score: domains.reduce((total, domain) => total + domain.score, 0),
      jobCount: jobs.size,
      skillCount: domains.reduce((total, domain) => total + domain.skillCount, 0),
      gapCount: domains.reduce((total, domain) => total + domain.gapCount, 0),
      adjacentCount: domains.reduce((total, domain) => total + domain.adjacentCount, 0),
      domains,
    }];
  });

  const jobsForSkill = (key: string): JobLite[] =>
    [...(jobsBySkill.get(key) ?? [])]
      .map((jobId) => jobById.get(jobId))
      .filter((job): job is JobLite => Boolean(job));

  const jobsForDomain = (domainId: string): JobLite[] => {
    const jobIds = new Set<number>();
    for (const skill of skills) {
      if ((skill.domainId ?? UNASSIGNED_ID) !== domainId) continue;
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
    domainRows,
    categoryRows,
    filteredJobCount: filteredJobs.length,
    jobsForSkill,
    jobsForDomain,
    companies: uniqueSorted(payload.jobs.map((job) => job.company)),
    seniorities: uniqueSorted(payload.jobs.map((job) => job.seniority)),
    statusCounts,
    persistedStateOf: (kind, key) => persistedStatus.get(targetId({ kind, key })),
  };
}
