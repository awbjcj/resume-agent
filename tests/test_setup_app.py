import pytest
from textual.widgets import Button, Checkbox, Footer, Input, Select, TextArea

from resume_agent.setup.app import SetupApp
from resume_agent.setup.screens import (
    ConfirmScreen,
    ConnectorsScreen,
    HandoffScreen,
    ProfileSourcesScreen,
    SearchScreen,
    SecretsScreen,
)
from resume_agent.setup.state import WizardState


def _press(screen, btn_id):
    """Invoke a button handler directly (headless mouse hit-testing is unreliable
    on the scrollable, centered wizard panels)."""
    screen.on_button_pressed(Button.Pressed(screen.query_one("#" + btn_id, Button)))


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


@pytest.mark.asyncio
async def test_wizard_advances_through_screens_and_assembles_state():
    captured = {}

    def fake_writer(state, root="."):
        captured["state"] = state
        return {"/x/.env": "written", "/x/config/search.yaml": "written"}

    app = SetupApp(state=WizardState(), writer=fake_writer, root="/x")
    async with app.run_test(headless=True, size=(120, 60)) as pilot:
        _press(app.screen, "continue")  # Welcome -> Secrets
        await pilot.pause()
        assert isinstance(app.screen, SecretsScreen)
        app.screen.query_one("#anthropic_key", Input).value = "sk-ant-test"
        await pilot.pause()
        _press(app.screen, "continue")  # Secrets -> Profile
        await pilot.pause()
        assert isinstance(app.screen, ProfileSourcesScreen)
        app.screen.query_one("#resume_path", Input).value = "resume.pdf"
        app.screen.query_one("#github_username", Input).value = "octocat"
        await pilot.pause()
        _press(app.screen, "continue")  # Profile -> Search
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        app.screen.query_one("#keywords", Input).value = "python, kafka"
        app.screen.query_one("#remote_policy", Select).value = "remote"
        await pilot.pause()
        _press(app.screen, "continue")  # Search -> Connectors
        await pilot.pause()
        assert isinstance(app.screen, ConnectorsScreen)
        app.screen.query_one("#greenhouse_enabled", Checkbox).value = True
        app.screen.query_one("#gh_boards", TextArea).text = "stripe, Stripe\nairbnb"
        await pilot.pause()
        _press(app.screen, "continue")  # Connectors -> Confirm
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        _press(app.screen, "write")  # writes, then -> Handoff
        await pilot.pause()
        assert isinstance(app.screen, HandoffScreen)

    # the injected writer received the fully assembled state
    s = captured["state"]
    assert s.anthropic_api_key == "sk-ant-test"
    assert s.resume_path == "resume.pdf"
    assert s.github_username == "octocat"
    assert s.keywords == ["python", "kafka"]
    assert s.remote_policy == "remote"
    assert s.greenhouse_enabled is True
    assert s.greenhouse_boards == [
        {"token": "stripe", "company": "Stripe"},
        {"token": "airbnb", "company": "Airbnb"},
    ]


@pytest.mark.asyncio
async def test_nav_buttons_stay_in_viewport_on_small_terminal():
    """Regression: the forward nav button must be on-screen (and above the
    Footer) on a standard 80x24 terminal.

    Before the docked-nav fix the tall scrolling screens (Secrets, Search,
    Connectors) laid the nav out below a mis-measured scroll region, so
    Continue was off-viewport and unreachable even by scrolling — exactly the
    "no continue button after search criteria" report. The older tests missed
    it because they call ``on_button_pressed`` directly at size (120, 60).
    """
    state = WizardState(
        anthropic_api_key="sk", resume_path="r.pdf", keywords=["python"], titles=["eng"]
    )
    app = SetupApp(state=state, writer=lambda s, root=".": {"x": "written"}, root="/x")
    screens = [
        SecretsScreen,
        ProfileSourcesScreen,
        SearchScreen,
        ConnectorsScreen,
        ConfirmScreen,
    ]
    async with app.run_test(size=(80, 24)) as pilot:
        for screen_cls in screens:
            app.push_screen(screen_cls())
            await pilot.pause()
            screen = app.screen
            forward = screen.query("#continue") or screen.query("#write")
            btn = forward.first(Button)
            footer = screen.query_one(Footer)
            name = screen_cls.__name__
            assert btn.region.y >= 0, f"{name}: nav button above viewport"
            assert btn.region.bottom <= app.size.height, (
                f"{name}: nav button below viewport"
            )
            assert btn.region.bottom <= footer.region.y, (
                f"{name}: nav button overlaps footer"
            )


@pytest.mark.asyncio
async def test_search_screen_clamps_unknown_remote_policy():
    """Regression: a re-run loading an existing search.yaml whose remote_policy
    is free text (e.g. "flexible") must not crash SearchScreen — the Select
    rejects unknown values, so on_mount clamps to "any"."""
    state = WizardState(keywords=["python"], remote_policy="flexible")
    app = SetupApp(state=state, writer=lambda s, root=".": {}, root="/x")
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(SearchScreen())
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        assert app.screen.query_one("#remote_policy", Select).value == "any"


@pytest.mark.asyncio
async def test_back_button_returns_to_previous_screen():
    app = SetupApp(state=WizardState(), writer=lambda s, root=".": {})
    async with app.run_test(headless=True, size=(120, 60)) as pilot:
        _press(app.screen, "continue")  # Welcome -> Secrets
        await pilot.pause()
        assert isinstance(app.screen, SecretsScreen)
        _press(app.screen, "back")  # Secrets -> Welcome
        await pilot.pause()
        assert not isinstance(app.screen, SecretsScreen)


def test_load_existing_state_survives_corrupt_config(tmp_path):
    """Regression: a corrupt existing config must not crash setup at launch.

    load_existing_state runs in SetupApp.__init__; before the per-section guard
    a malformed YAML (ParserError) or wrong-schema value (pydantic
    ValidationError) propagated out of the constructor and the wizard never
    started — exactly when a user runs setup to repair that config.
    """
    from resume_agent.setup.writer import load_existing_state

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "search.yaml").write_text(
        "keywords: [unclosed\n", encoding="utf-8"
    )  # malformed YAML
    (cfg / "connectors.yaml").write_text(
        "greenhouse: not-a-mapping\n", encoding="utf-8"
    )  # bad schema
    (cfg / "profile_sources.yaml").write_text(
        "resume_path: ok.pdf\n", encoding="utf-8"
    )  # valid

    state = load_existing_state(tmp_path)
    assert state.keywords == []  # bad search.yaml -> section defaults
    assert state.greenhouse_enabled is False  # bad connectors.yaml -> section defaults
    assert state.resume_path == "ok.pdf"  # valid file still loaded

    # The constructor path (state is None -> load_existing_state) must also survive.
    app = SetupApp(root=str(tmp_path), writer=lambda s, root=".": {})
    assert isinstance(app.state, WizardState)
