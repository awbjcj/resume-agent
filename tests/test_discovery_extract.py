import pytest

from resume_agent.llm_runner import AgentRunner

from resume_agent.models.job import (
    JobCriteria,
    JobCriteriaExtract,
    SalaryRangeExtract,
    SponsorshipSignal,
)
from resume_agent.discovery.extract import (
    _INSTRUCTIONS,
    build_extract_agent,
    extract_job_criteria,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _extract(**overrides):
    base = dict(
        sponsorship_signal=SponsorshipSignal.offered,
        seniority=None,
        employment_type=None,
        tech_stack=[],
        industry=None,
        company_size=None,
        yoe_min=None,
        salary_range=None,
        remote_policy=None,
        location=None,
        must_have_skills=[],
        nice_to_have_skills=[],
    )
    base.update(overrides)
    return JobCriteriaExtract.model_validate(base)


def test_extract_maps_readable_industry_candidate_and_passes_text():
    agent = _FakeAgent(_extract(industry="Fintech"))
    out = extract_job_criteria("jd text", agent)
    assert isinstance(out, JobCriteria)
    assert out.sponsorship_signal is SponsorshipSignal.offered
    assert out.industry == "Fintech"
    assert agent.received == "jd text"


def test_aextract_job_criteria_uses_arun_and_semaphore():
    import asyncio

    from resume_agent.discovery.extract import aextract_job_criteria

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            self.received = prompt
            return _FakeResult(_extract(industry="Autonomous Driving"))

    agent = _AsyncAgent()

    async def go():
        return await aextract_job_criteria("jd text", agent, sem=asyncio.Semaphore(2))

    out = asyncio.run(go())
    assert isinstance(out, JobCriteria)
    assert out.industry == "Autonomous Driving"
    assert agent.received == "jd text"


def test_extract_preserves_readable_industry_for_incremental_classification():
    out = _extract(industry="Financial Technology").to_criteria()

    assert out.industry == "Financial Technology"


def test_extract_fills_salary_defaults_for_null_currency_and_period():
    agent = _FakeAgent(
        _extract(
            salary_range=SalaryRangeExtract(
                minimum=100, maximum=200, currency=None, period=None
            )
        )
    )
    out = extract_job_criteria("jd", agent)
    assert out.salary_range is not None
    assert (out.salary_range.minimum, out.salary_range.maximum) == (100, 200)
    assert out.salary_range.currency == "USD"
    assert out.salary_range.period == "year"


def test_extract_preserves_fractional_hourly_salary():
    extracted = _extract(
        salary_range={
            "minimum": 41.75,
            "maximum": 66.75,
            "currency": "USD",
            "period": "hour",
        }
    )

    out = extracted.to_criteria()

    assert out.salary_range is not None
    assert (out.salary_range.minimum, out.salary_range.maximum) == (41.75, 66.75)
    assert out.salary_range.period == "hour"


def test_extract_rejects_wrong_type():
    with pytest.raises(TypeError):
        extract_job_criteria("x", _FakeAgent("nope"))


def test_extraction_schema_within_anthropic_limits():
    """Guards the root cause of the historical 'Schema is too complex' 400.

    Anthropic's structured-output compiler doubles state space per optional
    field; the extraction schema must therefore stay at zero optional params
    and within the 16 union-typed-parameter ceiling.
    """
    transform_schema = pytest.importorskip("anthropic").transform_schema
    schema = transform_schema(JobCriteriaExtract.model_json_schema())

    counts = {"optional": 0, "union": 0}

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and "properties" in node:
            required = set(node.get("required", []))
            for key, value in node["properties"].items():
                if key not in required:
                    counts["optional"] += 1
                if isinstance(value, dict) and "anyOf" in value:
                    counts["union"] += 1
                walk(value)
        for sub in node.get("$defs", {}).values():
            walk(sub)

    walk(schema)
    assert counts["optional"] == 0, (
        f"optional params must be 0, got {counts['optional']}"
    )
    assert counts["union"] <= 16, f"union params must be <=16, got {counts['union']}"


def test_extract_coerces_null_list_fields_to_empty():
    """JSON-mode providers honour 'leave unknown fields null' literally, emitting
    ``null`` for empty list fields. The schema is non-nullable (zero optionals,
    to satisfy Anthropic's grammar compiler), so a before-validator must coerce
    ``None`` -> ``[]`` rather than letting validation fail and the job be skipped.
    """
    base = dict(
        sponsorship_signal=SponsorshipSignal.silent,
        seniority=None,
        employment_type=None,
        tech_stack=None,
        industry=None,
        company_size=None,
        yoe_min=None,
        salary_range=None,
        remote_policy=None,
        location=None,
        must_have_skills=None,
        nice_to_have_skills=None,
    )
    extract = JobCriteriaExtract.model_validate(base)
    assert extract.tech_stack == []
    assert extract.must_have_skills == []
    assert extract.nice_to_have_skills == []


def test_build_extract_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(
        build_extract_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner
    )


def test_build_extract_agent_disables_agno_retry(monkeypatch):
    # agno's own retry is off (retries=0) — AgentRunner retries transient
    # failures itself, behind the is_transient predicate.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from resume_agent.config import env_settings

    env_settings.cache_clear()
    try:
        runner = build_extract_agent(model_id="claude-haiku-4-5-20251001")
        agent = runner._agent  # AgentRunner wraps the agno Agent
        assert agent.retries == 0
    finally:
        env_settings.cache_clear()


def test_instructions_mention_new_fields():
    joined = " ".join(_INSTRUCTIONS).lower()
    for needle in [
        "seniority",
        "employment type",
        "tech stack",
        "industry",
        "company size",
    ]:
        assert needle in joined


def test_instructions_require_atomic_skills_and_size_buckets():
    joined = " ".join(_INSTRUCTIONS).lower()
    assert "one skill" in joined or "single" in joined  # atomic-skills guidance
    assert "startup" in joined and "scaleup" in joined and "enterprise" in joined


def test_instructions_require_human_readable_business_domain():
    joined = " ".join(_INSTRUCTIONS).lower()
    assert "human-readable" in joined
    assert "business domain" in joined
    assert "job function" in joined
    assert "null" in joined


def test_extract_instructions_capture_soft_skills():
    joined = " ".join(_INSTRUCTIONS).lower()
    assert "interpersonal" in joined or "soft" in joined
