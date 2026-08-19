from resume_agent.matching.observability import build_uccm_observation


def test_uccm_observation_records_required_privacy_safe_distributions():
    observation = build_uccm_observation(
        assertion_statuses=["evidenced", "inferred", "evidenced"],
        assertion_types=["skill", "skill", "knowledge"],
        requirement_types=["skill", "unknown", "credential", "unknown"],
        match_statuses=["verified_exact", "unknown", "credential_gap"],
        correction_count=1,
        false_transfer_adjudications=2,
        fallback=True,
        stale=True,
        provider_cost_micros=125,
        provider_latency_ms=42.5,
    )

    assert observation.profile_assertions_by_status == {
        "evidenced": 2,
        "inferred": 1,
    }
    assert observation.profile_assertions_by_type == {"knowledge": 1, "skill": 2}
    assert observation.unresolved_term_rate == 0.5
    assert observation.match_status_distribution == {
        "credential_gap": 1,
        "unknown": 1,
        "verified_exact": 1,
    }
    assert observation.correction_rate == 1 / 7
    assert observation.false_transfer_adjudications == 2
    assert observation.fallback_rate == 1.0
    assert observation.stale_artifact_incidents == 1
    assert observation.provider_cost_micros == 125
    assert observation.provider_latency_ms == 42.5


def test_uccm_observation_uses_zero_rates_for_empty_inputs():
    observation = build_uccm_observation(
        assertion_statuses=[],
        assertion_types=[],
        requirement_types=[],
        match_statuses=[],
    )

    assert observation.unresolved_term_rate == 0.0
    assert observation.correction_rate == 0.0
    assert observation.provider_cost_micros is None
    assert observation.provider_latency_ms is None
