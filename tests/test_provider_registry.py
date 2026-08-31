from resume_tailor_harness.config import Settings
from resume_tailor_harness.llm_routing import (
    DIRECT_API_BASE_URL_FIELDS,
    ROUTE_MODE_FIELDS,
    SUB2API_KEY_FIELDS,
)
from resume_tailor_harness.provider_registry import PROVIDERS, PROVIDER_SPECS


def test_provider_registry_references_real_settings_fields():
    fields = Settings.model_fields
    for spec in PROVIDER_SPECS:
        assert spec.api_key_field in fields
        assert spec.subscription_key_field in fields
        assert spec.route_mode_field in fields
        if spec.direct_base_url_field is not None:
            assert spec.direct_base_url_field in fields


def test_routing_maps_are_derived_from_the_provider_registry():
    assert tuple(SUB2API_KEY_FIELDS) == PROVIDERS
    assert tuple(ROUTE_MODE_FIELDS) == PROVIDERS
    assert set(DIRECT_API_BASE_URL_FIELDS).issubset(PROVIDERS)
