import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, cast

from sqlmodel import Session, select

from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.tables import Job, JobStatus

if TYPE_CHECKING:
    from resume_agent.tracking.skill_clusters import ClusterMap

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


@dataclass
class SkillNode:
    skill: str
    theme_id: str | None
    covered: bool


@dataclass
class ThemeNode:
    id: str
    label: str


@dataclass
class DemandGraph:
    target_total: int
    clusters_stale: bool
    jobs: list[JobLite]
    skills: list[SkillNode]
    edges: list[DemandEdge]
    themes: list[ThemeNode]


@dataclass
class GapRow:
    """One missing skill, aggregated across target jobs."""

    skill: str
    demand_count: int
    target_total: int

    @property
    def demand_share(self) -> int:
        return round(100 * self.demand_count / self.target_total) if self.target_total else 0


@dataclass
class MatchGapReport:
    target_total: int
    gaps: list[GapRow]
    per_job: dict[int, list[str]]


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
) -> DemandGraph:
    """Build normalized target-job skill demand for dashboard consumers."""
    target_jobs = _target_jobs(session)
    profile_tokens = profile_skill_tokens(facts)
    jobs: list[JobLite] = []
    skill_nodes: dict[str, SkillNode] = {}
    edges: list[DemandEdge] = []

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

        emitted: set[tuple[str, SkillSource]] = set()
        for key, source in _SKILL_SOURCES:
            for raw_skill in _criteria_skill_values(job, key):
                skill = normalize_skill(raw_skill)
                edge_key = (skill, source)
                if not skill or edge_key in emitted:
                    continue
                emitted.add(edge_key)
                skill_nodes.setdefault(
                    skill,
                    SkillNode(
                        skill=skill,
                        theme_id=None,
                        covered=skill in profile_tokens,
                    ),
                )
                edges.append(DemandEdge(job_id=job.id, skill=skill, source=source))

    themes: list[ThemeNode] = []
    return DemandGraph(
        target_total=len(jobs),
        clusters_stale=bool(skill_nodes) and not themes,
        jobs=jobs,
        skills=list(skill_nodes.values()),
        edges=edges,
        themes=themes,
    )


def match_gap(
    session: Session,
    facts: ProfileFacts,
    canonicalizer: Canonicalizer | None = None,
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

    canonical = canonicalizer(all_tokens) if canonicalizer else {token: token for token in all_tokens}
    profile_canonical = {canonical.get(token, token) for token in profile_tokens}

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
        GapRow(skill=display_for[token], demand_count=count, target_total=target_total)
        for token, count in demand.items()
    ]
    gaps.sort(key=lambda gap: (-gap.demand_count, gap.skill.lower()))
    return MatchGapReport(target_total=target_total, gaps=gaps, per_job=per_job)
