import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal, cast

from sqlmodel import Session, select

from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.tables import Job, JobStatus

if TYPE_CHECKING:
    from resume_agent.taxonomy.clusters import ClusterMap
    from resume_agent.taxonomy.corrections import TaxonomyCorrections

_PUNCT = re.compile(r"[^a-z0-9+#. ]+")
_WS = re.compile(r"\s+")

TARGET_STATUSES = (
    JobStatus.shortlisted.value,
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
)

Canonicalizer = Callable[[set[str]], dict[str, str]]
SkillSource = Literal["must", "nice", "tech"]

_SKILL_SOURCES: tuple[tuple[str, SkillSource], ...] = (
    ("must_have_skills", "must"),
    ("nice_to_have_skills", "nice"),
    ("tech_stack", "tech"),
)


def normalize_skill(skill: str) -> str:
    """Lowercase, drop most punctuation, and collapse whitespace for matching."""
    s = skill.lower()
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def profile_skill_tokens(facts: ProfileFacts) -> set[str]:
    """Every profile skill name and alias, normalized as a lookup set."""
    tokens: set[str] = set()
    for skill_list in facts.skills.values():
        for skill in skill_list:
            tokens.add(normalize_skill(skill.name))
            for alias in skill.aliases:
                tokens.add(normalize_skill(alias))
    tokens.discard("")
    return tokens


@dataclass
class JobLite:
    id: int
    company: str | None
    title: str | None
    seniority: str | None


@dataclass
class DemandEdge:
    job_id: int
    skill: str
    source: SkillSource
    skill_key: str = ""


@dataclass
class SkillNode:
    skill: str
    domain_id: str | None
    covered: bool
    key: str = ""
    members: dict[str, int] = field(default_factory=dict)
    must: int = 0
    nice: int = 0
    tech: int = 0
    job_count: int = 0
    coverage: Literal["covered", "adjacent", "gap"] = "gap"

    def __post_init__(self) -> None:
        if self.covered or self.coverage == "covered":
            self.covered = True
            self.coverage = "covered"
        else:
            self.covered = False


@dataclass
class DomainNode:
    id: str
    label: str
    essential_score: int = 0
    popular_score: int = 0
    job_count: int = 0
    skill_count: int = 0
    gap_count: int = 0
    adjacent_count: int = 0
    category: str = "other"


@dataclass
class CategoryNode:
    slug: str
    label: str
    kind: Literal["hard", "soft"]


@dataclass
class DemandGraph:
    target_total: int
    clusters_stale: bool
    jobs: list[JobLite]
    skills: list[SkillNode]
    edges: list[DemandEdge]
    domains: list[DomainNode]
    categories: list[CategoryNode] = field(default_factory=list)


@dataclass
class GapRow:
    """One missing skill, aggregated across target jobs."""

    skill: str
    demand_count: int
    target_total: int
    adjacent: bool = False

    @property
    def demand_share(self) -> int:
        return round(100 * self.demand_count / self.target_total) if self.target_total else 0


@dataclass
class MatchGapReport:
    target_total: int
    gaps: list[GapRow]
    per_job: dict[int, list[str]]


@dataclass
class _SkillAccumulator:
    member_jobs: dict[str, set[int]] = field(default_factory=dict)
    source_jobs: dict[SkillSource, set[int]] = field(
        default_factory=lambda: {"must": set(), "nice": set(), "tech": set()}
    )
    job_ids: set[int] = field(default_factory=set)


def _target_jobs(session: Session) -> list[Job]:
    status_col = cast(Any, Job.status)
    id_col = cast(Any, Job.id)
    archived_col = cast(Any, Job.archived_at)
    return list(
        session.exec(
            select(Job)
            .where(status_col.in_(TARGET_STATUSES), archived_col.is_(None))
            .order_by(id_col)
        ).all()
    )


def _must_have_skills(job: Job) -> list[str]:
    raw = (job.criteria_json or {}).get("must_have_skills") or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [str(skill) for skill in raw if str(skill).strip()]


def _criteria_skill_values(job: Job, key: str) -> list[str]:
    raw = (job.criteria_json or {}).get(key) or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, Collection) or isinstance(raw, (Mapping, bytes)):
        return []
    return [str(skill) for skill in raw if str(skill).strip()]


def collect_target_skill_tokens(session: Session) -> set[str]:
    tokens: set[str] = set()
    for job in _target_jobs(session):
        for key, _source in _SKILL_SOURCES:
            for skill in _criteria_skill_values(job, key):
                if token := normalize_skill(skill):
                    tokens.add(token)
    return tokens


def build_demand_graph(
    session: Session,
    facts: ProfileFacts,
    cluster_map: "ClusterMap | None" = None,
    *,
    corrections: "TaxonomyCorrections | None" = None,
) -> DemandGraph:
    """Build normalized target-job skill demand for dashboard consumers."""
    from resume_agent.taxonomy.corrections import (
        TaxonomyCorrections,
        added_canonical_tokens,
        removed_canonical_tokens,
    )
    from resume_agent.taxonomy.vocabulary import SKILL_GROUPS, category_kind

    corrections = corrections or TaxonomyCorrections()
    target_jobs = _target_jobs(session)
    profile_tokens = profile_skill_tokens(facts)
    aliases = cluster_map.aliases if cluster_map else {}
    domain_of = cluster_map.domain_of if cluster_map else {}
    domain_label = cluster_map.domain_label if cluster_map else {}
    category_of = cluster_map.category_of if cluster_map else {}
    removed = removed_canonical_tokens(corrections, aliases)
    profile_canonical = {aliases.get(token, token) for token in profile_tokens}
    covered_themes = {
        domain_of[token] for token in profile_canonical if token in domain_of
    }
    jobs: list[JobLite] = []
    accumulators: dict[str, _SkillAccumulator] = {}
    edge_keys: set[tuple[int, str, SkillSource]] = set()

    for job in target_jobs:
        if job.id is None:
            continue
        criteria = job.criteria_json or {}
        seniority = criteria.get("seniority")
        jobs.append(
            JobLite(
                id=job.id,
                company=job.company,
                title=job.title,
                seniority=seniority if isinstance(seniority, str) else None,
            )
        )

        for key, source in _SKILL_SOURCES:
            for raw_skill in _criteria_skill_values(job, key):
                token = normalize_skill(raw_skill)
                canonical = aliases.get(token, token)
                if not canonical or canonical in removed:
                    continue
                phrasing = raw_skill.strip()
                accumulator = accumulators.setdefault(canonical, _SkillAccumulator())
                accumulator.member_jobs.setdefault(phrasing, set()).add(job.id)
                accumulator.source_jobs[source].add(job.id)
                accumulator.job_ids.add(job.id)
                edge_keys.add((job.id, canonical, source))

    display_by_key: dict[str, str] = {}
    for canonical in sorted(added_canonical_tokens(corrections, aliases) - removed):
        accumulators.setdefault(canonical, _SkillAccumulator())
    skill_nodes: list[SkillNode] = []
    for canonical, accumulator in sorted(accumulators.items()):
        members = {
            phrasing: len(job_ids)
            for phrasing, job_ids in sorted(
                accumulator.member_jobs.items(), key=lambda item: (item[0].casefold(), item[0])
            )
        }
        display = (
            min(
                members,
                key=lambda phrasing: (-members[phrasing], phrasing.casefold(), phrasing),
            )
            if members
            else canonical
        )
        display_by_key[canonical] = display
        if canonical in profile_canonical:
            coverage: Literal["covered", "adjacent", "gap"] = "covered"
        elif domain_of.get(canonical) in covered_themes:
            coverage = "adjacent"
        else:
            coverage = "gap"
        skill_nodes.append(
            SkillNode(
                skill=display,
                domain_id=domain_of.get(canonical),
                covered=coverage == "covered",
                key=canonical,
                members=members,
                must=len(accumulator.source_jobs["must"]),
                nice=len(accumulator.source_jobs["nice"]),
                tech=len(accumulator.source_jobs["tech"]),
                job_count=len(accumulator.job_ids),
                coverage=coverage,
            )
        )

    source_order = {source: index for index, source in enumerate(("must", "nice", "tech"))}
    edges = [
        DemandEdge(
            job_id=job_id,
            skill=display_by_key[skill_key],
            source=source,
            skill_key=skill_key,
        )
        for job_id, skill_key, source in sorted(
            edge_keys,
            key=lambda edge: (edge[0], source_order[edge[2]], edge[1]),
        )
    ]

    nodes_by_domain: dict[str, list[SkillNode]] = {}
    for node in skill_nodes:
        if node.domain_id is not None:
            nodes_by_domain.setdefault(node.domain_id, []).append(node)
    domains = [
        DomainNode(
            id=domain_id,
            label=domain_label.get(domain_id, domain_id),
            essential_score=sum(
                node.must * 3 + node.nice * 2 + node.tech for node in domain_nodes
            ),
            popular_score=sum(node.job_count for node in domain_nodes),
            job_count=len(
                set().union(
                    set(), *(accumulators[node.key].job_ids for node in domain_nodes)
                )
            ),
            skill_count=len(domain_nodes),
            gap_count=sum(node.coverage == "gap" for node in domain_nodes),
            adjacent_count=sum(node.coverage == "adjacent" for node in domain_nodes),
            category=category_of.get(domain_id, "other"),
        )
        for domain_id, domain_nodes in sorted(nodes_by_domain.items())
    ]
    categories = [
        CategoryNode(slug=slug, label=label, kind=category_kind(slug))
        for slug, label in SKILL_GROUPS.items()
    ]
    return DemandGraph(
        target_total=len(jobs),
        clusters_stale=any(node.domain_id is None for node in skill_nodes),
        jobs=jobs,
        skills=skill_nodes,
        edges=edges,
        domains=domains,
        categories=categories,
    )


def match_gap(
    session: Session,
    facts: ProfileFacts,
    canonicalizer: Canonicalizer | None = None,
    *,
    cluster_map: "ClusterMap | None" = None,
) -> MatchGapReport:
    """Skills demanded by target jobs that the profile does not cover."""
    job_reqs: list[tuple[int, list[tuple[str, str]]]] = []
    all_tokens: set[str] = set()
    for job in _target_jobs(session):
        if job.id is None:
            continue
        pairs: list[tuple[str, str]] = []
        for skill in _must_have_skills(job):
            token = normalize_skill(skill)
            if not token:
                continue
            pairs.append((token, skill))
            all_tokens.add(token)
        job_reqs.append((job.id, pairs))

    profile_tokens = profile_skill_tokens(facts)
    all_tokens |= profile_tokens

    if cluster_map is not None:
        canonical = {
            token: cluster_map.aliases.get(token, token) for token in all_tokens
        }
    else:
        canonical = (
            canonicalizer(all_tokens)
            if canonicalizer
            else {token: token for token in all_tokens}
        )
    profile_canonical = {canonical.get(token, token) for token in profile_tokens}
    covered_themes = (
        {
            cluster_map.domain_of[token]
            for token in profile_canonical
            if token in cluster_map.domain_of
        }
        if cluster_map is not None
        else set()
    )

    per_job: dict[int, list[str]] = {}
    demand: dict[str, int] = {}
    display_for: dict[str, str] = {}
    for job_id, pairs in job_reqs:
        requested: dict[str, str] = {}
        for token, display in pairs:
            requested.setdefault(canonical.get(token, token), display)

        missing = [display for token, display in requested.items() if token not in profile_canonical]
        per_job[job_id] = missing

        for token, display in requested.items():
            if token in profile_canonical:
                continue
            demand[token] = demand.get(token, 0) + 1
            display_for.setdefault(token, display)

    target_total = len(job_reqs)
    gaps = [
        GapRow(
            skill=display_for[token],
            demand_count=count,
            target_total=target_total,
            adjacent=(
                cluster_map is not None
                and cluster_map.domain_of.get(token) in covered_themes
            ),
        )
        for token, count in demand.items()
    ]
    gaps.sort(key=lambda gap: (-gap.demand_count, gap.skill.lower()))
    return MatchGapReport(target_total=target_total, gaps=gaps, per_job=per_job)
