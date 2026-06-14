import pytest

from resume_agent.setup.app import SetupApp
from resume_agent.setup.state import WizardState


def test_perform_write_calls_injected_writer():
    calls = {}

    def fake_writer(state, root="."):
        calls["state"] = state
        return {"/x/.env": "written"}

    app = SetupApp(state=WizardState(anthropic_api_key="sk-x"), writer=fake_writer)
    report = app._perform_write()
    assert report == {"/x/.env": "written"}
    assert calls["state"].anthropic_api_key == "sk-x"


@pytest.mark.asyncio
async def test_app_boots_without_error():
    app = SetupApp(state=WizardState(), writer=lambda s, root=".": {})
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_running
