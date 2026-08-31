from resume_tailor_harness.discovery.search_config import SearchConfig


def test_relevance_fields_default_empty_and_optional():
    c = SearchConfig()
    assert c.role_anchors == []
    assert c.exclude_terms == []
    assert c.target_role is None
    assert c.distance is None
    assert c.max_days_old is None
    assert c.experience_levels == []
    assert c.employment_types == []


def test_relevance_fields_roundtrip():
    c = SearchConfig.model_validate(
        {
            "role_anchors": ["engineer", "ai"],
            "exclude_terms": ["driver", "creative"],
            "target_role": "Applied AI / LLM engineering roles.",
            "distance": 40,
            "max_days_old": 30,
            "experience_levels": ["mid-senior", "director"],
            "employment_types": ["full_time"],
        }
    )
    assert c.role_anchors == ["engineer", "ai"]
    assert c.exclude_terms == ["driver", "creative"]
    assert "Applied AI" in (c.target_role or "")
    assert c.distance == 40
    assert c.max_days_old == 30
    assert c.experience_levels == ["mid-senior", "director"]
    assert c.employment_types == ["full_time"]
