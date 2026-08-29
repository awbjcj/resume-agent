"""Textual wizard screens for resume-agent setup.

Screen order (spec §5.2):
  WelcomeScreen        — preflight: python / uv / chromium / examples   [step 0]
  SecretsScreen        — ANTHROPIC_API_KEY, tokens, optional creds       [step 1]
  ProfileSourcesScreen — resume path + GitHub username                   [step 2]
  SearchScreen         — keywords / titles / locations + hard filters    [step 3]
  ConnectorsScreen     — Greenhouse / Adzuna / RemoteOK / LinkedIn       [step 4]
  ConfirmScreen        — per-file plan, then atomic_write_all            [step 6]
  HandoffScreen        — write recap + exact next commands               [step 8]
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

from resume_agent.setup.preflight import (
    check_chromium,
    check_examples_present,
    check_python,
    check_uv,
)
from resume_agent.setup.validate import anthropic_ping
from resume_agent.setup.yaml_gen import parse_greenhouse_boards, parse_list

if TYPE_CHECKING:
    from resume_agent.setup.app import SetupApp


class WelcomeScreen(Screen[None]):
    """Step 1 of 7 — environment preflight checks."""

    TITLE = "Resume Agent Setup  ·  1 / 7  ·  Preflight"

    CSS = """
    WelcomeScreen { align: center top; }
    WelcomeScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    WelcomeScreen #heading { text-style: bold; margin-bottom: 1; }
    WelcomeScreen #remedy  { height: auto; margin: 1 0; }
    WelcomeScreen #body    { height: 1fr; align: center top; }
    WelcomeScreen .nav     { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Checking your environment…", id="heading")
                    yield DataTable(id="checks", show_cursor=False)
                    yield Static("", id="remedy")
            with Horizontal(classes="nav"):
                yield Button("Quit", id="quit")
                yield Button(
                    "Continue →", id="continue", variant="primary", disabled=True
                )
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        table = self.query_one("#checks", DataTable)
        table.add_columns("Check", "", "Detail")

        results = [
            check_python(),
            check_uv(),
            check_chromium(),
            check_examples_present(app.root),
        ]

        blocking = False
        remedies: list[str] = []
        for r in results:
            icon = (
                Text("✓", style="bold green") if r.ok else Text("✗", style="bold red")
            )
            table.add_row(r.name, icon, r.detail)
            if not r.ok:
                if r.name in ("python", "examples"):
                    blocking = True
                if r.remedy:
                    remedies.append(f"  • {r.name}: {r.remedy}")

        if remedies:
            self.query_one("#remedy", Static).update(
                "[yellow]" + "\n".join(remedies) + "[/yellow]"
            )
        self.query_one("#continue", Button).disabled = blocking

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        elif event.button.id == "continue":
            self.app.push_screen(SecretsScreen())


class SecretsScreen(Screen[None]):
    """Step 2 of 7 — API keys and service credentials written to .env."""

    TITLE = "Resume Agent Setup  ·  2 / 7  ·  Secrets"

    CSS = """
    SecretsScreen { align: center top; }
    SecretsScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    SecretsScreen .section { text-style: bold; margin-top: 1; }
    SecretsScreen .hint    { margin-top: 1; }
    SecretsScreen #status  { height: 2; margin: 1 0; }
    SecretsScreen #body    { height: 1fr; align: center top; }
    SecretsScreen .nav     { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("API keys and credentials", id="heading")

                    yield Static("Required", classes="section")
                    yield Label("Anthropic API key", classes="hint")
                    yield Input(
                        id="anthropic_key", placeholder="sk-ant-api03-…", password=True
                    )

                    yield Static("Optional — GitHub", classes="section")
                    yield Label(
                        "GitHub token  (public repos used if omitted)", classes="hint"
                    )
                    yield Input(id="github_token", placeholder="ghp_…", password=True)

                    yield Static("Optional — Adzuna connector", classes="section")
                    yield Label("App ID", classes="hint")
                    yield Input(id="adzuna_app_id", placeholder="xxxxxxxx")
                    yield Label("App key", classes="hint")
                    yield Input(
                        id="adzuna_app_key",
                        placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        password=True,
                    )

                    yield Static("Optional — LinkedIn scraper", classes="section")
                    yield Label("Email", classes="hint")
                    yield Input(id="linkedin_email", placeholder="you@example.com")
                    yield Label("Password", classes="hint")
                    yield Input(
                        id="linkedin_password", placeholder="••••••••", password=True
                    )

                    yield Static("", id="status")

            with Horizontal(classes="nav"):
                yield Button("← Back", id="back")
                yield Button("Validate key", id="validate")
                yield Button(
                    "Continue →", id="continue", variant="primary", disabled=True
                )
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        self.query_one("#anthropic_key", Input).value = s.anthropic_api_key
        self.query_one("#github_token", Input).value = s.github_token
        self.query_one("#adzuna_app_id", Input).value = s.adzuna_app_id
        self.query_one("#adzuna_app_key", Input).value = s.adzuna_app_key
        self.query_one("#linkedin_email", Input).value = s.linkedin_email
        self.query_one("#linkedin_password", Input).value = s.linkedin_password
        self._refresh_continue()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._refresh_continue()

    def _ready_to_continue(self) -> bool:
        """True when the minimum required input is present.

        Policy: ANTHROPIC_API_KEY must be non-empty. Validation is encouraged
        via the "Validate key" button but is not blocking — the wizard should
        not require a network round-trip to advance.
        """
        return bool(self.query_one("#anthropic_key", Input).value.strip())

    def _refresh_continue(self) -> None:
        self.query_one("#continue", Button).disabled = not self._ready_to_continue()

    def _save_to_state(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        s.anthropic_api_key = self.query_one("#anthropic_key", Input).value.strip()
        s.github_token = self.query_one("#github_token", Input).value.strip()
        s.adzuna_app_id = self.query_one("#adzuna_app_id", Input).value.strip()
        s.adzuna_app_key = self.query_one("#adzuna_app_key", Input).value.strip()
        s.linkedin_email = self.query_one("#linkedin_email", Input).value.strip()
        s.linkedin_password = self.query_one("#linkedin_password", Input).value.strip()

    @work(thread=True)
    def _do_validate(self) -> None:
        key = self.query_one("#anthropic_key", Input).value.strip()
        self.call_from_thread(  # type: ignore[attr-defined]
            self.query_one("#status", Static).update, "[yellow]Validating…[/yellow]"
        )
        result = anthropic_ping(key)
        msg = (
            "[bold green]✓ Key accepted[/bold green]"
            if result.ok
            else f"[bold red]✗ {result.detail}[/bold red]"
        )
        self.call_from_thread(self.query_one("#status", Static).update, msg)  # type: ignore[attr-defined]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "validate":
            self._do_validate()
        elif event.button.id == "continue":
            self._save_to_state()
            self.app.push_screen(ProfileSourcesScreen())


class ProfileSourcesScreen(Screen[None]):
    """Step 3 of 7 — where your resume lives and which GitHub to mine."""

    TITLE = "Resume Agent Setup  ·  3 / 7  ·  Profile sources"

    CSS = """
    ProfileSourcesScreen { align: center top; }
    ProfileSourcesScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    ProfileSourcesScreen .hint   { margin-top: 1; }
    ProfileSourcesScreen #resume_status { height: 1; }
    ProfileSourcesScreen #body   { height: 1fr; align: center top; }
    ProfileSourcesScreen .nav    { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Profile sources", id="heading")

                    yield Label("Resume file path  (PDF or DOCX)", classes="hint")
                    yield Input(id="resume_path", placeholder="data/profile/resume.pdf")
                    yield Static("", id="resume_status")

                    yield Label(
                        "GitHub username  (optional — mines public repos)",
                        classes="hint",
                    )
                    yield Input(id="github_username", placeholder="octocat")

            with Horizontal(classes="nav"):
                yield Button("← Back", id="back")
                yield Button(
                    "Continue →", id="continue", variant="primary", disabled=True
                )
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        self.query_one("#resume_path", Input).value = s.resume_path
        self.query_one("#github_username", Input).value = s.github_username
        self._refresh()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._refresh()

    def _resume_path(self) -> str:
        return self.query_one("#resume_path", Input).value.strip()

    def _refresh(self) -> None:
        """Continue requires a resume path; warn (don't block) if it's missing on disk."""
        path = self._resume_path()
        status = self.query_one("#resume_status", Static)
        if not path:
            status.update("")
        elif Path(path).expanduser().exists():
            status.update("[green]✓ file found[/green]")
        else:
            status.update(
                "[yellow]⚠ no file at that path yet (you can fix it later)[/yellow]"
            )
        self.query_one("#continue", Button).disabled = not path

    def _save_to_state(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        app.state.resume_path = self._resume_path()
        app.state.github_username = self.query_one(
            "#github_username", Input
        ).value.strip()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "continue":
            self._save_to_state()
            self.app.push_screen(SearchScreen())


class SearchScreen(Screen[None]):
    """Step 4 of 7 — what to search for and the hard filters to apply."""

    TITLE = "Resume Agent Setup  ·  4 / 7  ·  Search & filters"

    _REMOTE_OPTIONS = [
        ("Any", "any"),
        ("Remote only", "remote"),
        ("Hybrid", "hybrid"),
        ("On-site", "onsite"),
    ]

    CSS = """
    SearchScreen { align: center top; }
    SearchScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    SearchScreen .hint    { margin-top: 1; }
    SearchScreen .row     { height: auto; }
    SearchScreen .col     { width: 1fr; padding-right: 1; }
    SearchScreen #body    { height: 1fr; align: center top; }
    SearchScreen .nav     { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Search criteria & hard filters", id="heading")

                    yield Label(
                        "Keywords  (comma- or newline-separated)", classes="hint"
                    )
                    yield Input(
                        id="keywords", placeholder="python, distributed systems, kafka"
                    )

                    yield Label("Job titles", classes="hint")
                    yield Input(
                        id="titles", placeholder="Backend Engineer, Platform Engineer"
                    )

                    yield Label("Locations", classes="hint")
                    yield Input(id="locations", placeholder="Remote, New York, London")

                    yield Label("Remote policy", classes="hint")
                    yield Select(
                        self._REMOTE_OPTIONS,
                        id="remote_policy",
                        value="any",
                        allow_blank=False,
                    )

                    with Horizontal(classes="row"):
                        with Vertical(classes="col"):
                            yield Label("Min salary (optional)", classes="hint")
                            yield Input(
                                id="min_salary", type="integer", placeholder="120000"
                            )
                        with Vertical(classes="col"):
                            yield Label("Min years exp.", classes="hint")
                            yield Input(id="yoe_min", type="integer", placeholder="0")
                        with Vertical(classes="col"):
                            yield Label("Max years exp.", classes="hint")
                            yield Input(id="yoe_max", type="integer", placeholder="8")

                    yield Checkbox(
                        "Require visa sponsorship", id="sponsorship_required"
                    )

            with Horizontal(classes="nav"):
                yield Button("← Back", id="back")
                yield Button(
                    "Continue →", id="continue", variant="primary", disabled=True
                )
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        self.query_one("#keywords", Input).value = ", ".join(s.keywords)
        self.query_one("#titles", Input).value = ", ".join(s.titles)
        self.query_one("#locations", Input).value = ", ".join(s.locations)
        # Clamp to a known option: an existing search.yaml may hold a free-text
        # remote_policy (e.g. "flexible") that the Select would reject, crashing
        # the screen mount on re-run.
        valid_policies = {value for _, value in self._REMOTE_OPTIONS}
        self.query_one("#remote_policy", Select).value = (
            s.remote_policy if s.remote_policy in valid_policies else "any"
        )
        self.query_one("#min_salary", Input).value = (
            "" if s.min_salary is None else str(s.min_salary)
        )
        self.query_one("#yoe_min", Input).value = (
            "" if s.yoe_min is None else str(s.yoe_min)
        )
        self.query_one("#yoe_max", Input).value = (
            "" if s.yoe_max is None else str(s.yoe_max)
        )
        self.query_one("#sponsorship_required", Checkbox).value = s.sponsorship_required
        self._refresh()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._refresh()

    def _refresh(self) -> None:
        """Continue requires at least one keyword or title to search on."""
        has_terms = bool(
            parse_list(self.query_one("#keywords", Input).value)
            or parse_list(self.query_one("#titles", Input).value)
        )
        self.query_one("#continue", Button).disabled = not has_terms

    @staticmethod
    def _optional_int(raw: str) -> int | None:
        raw = raw.strip()
        return int(raw) if raw else None

    def _save_to_state(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        s.keywords = parse_list(self.query_one("#keywords", Input).value)
        s.titles = parse_list(self.query_one("#titles", Input).value)
        s.locations = parse_list(self.query_one("#locations", Input).value)
        s.remote_policy = str(self.query_one("#remote_policy", Select).value)
        s.min_salary = self._optional_int(self.query_one("#min_salary", Input).value)
        s.yoe_min = self._optional_int(self.query_one("#yoe_min", Input).value)
        s.yoe_max = self._optional_int(self.query_one("#yoe_max", Input).value)
        s.sponsorship_required = self.query_one("#sponsorship_required", Checkbox).value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "continue":
            self._save_to_state()
            self.app.push_screen(ConnectorsScreen())


class ConnectorsScreen(Screen[None]):
    """Step 5 of 7 — which job sources to pull from."""

    TITLE = "Resume Agent Setup  ·  5 / 7  ·  Connectors"

    CSS = """
    ConnectorsScreen { align: center top; }
    ConnectorsScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    ConnectorsScreen .hint    { margin-top: 1; color: $text-muted; }
    ConnectorsScreen #gh_boards { height: 5; margin-top: 1; }
    ConnectorsScreen #adzuna_warn { height: auto; }
    ConnectorsScreen #body    { height: 1fr; align: center top; }
    ConnectorsScreen .nav     { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Job-source connectors", id="heading")
                    yield Static(
                        "Enable any sources you want `resume-agent pull` to hit. "
                        "All are optional — you can also add jobs manually.",
                        classes="hint",
                    )

                    yield Checkbox(
                        "Greenhouse  (company job boards)", id="greenhouse_enabled"
                    )
                    yield Label(
                        "Boards — one per line: `token` or `token, Company Name`",
                        classes="hint",
                    )
                    yield TextArea(id="gh_boards")

                    yield Checkbox(
                        "Adzuna  (job-search aggregator)", id="adzuna_enabled"
                    )
                    yield Label("Adzuna country code (e.g. us, gb, de)", classes="hint")
                    yield Input(id="adzuna_country", placeholder="us")
                    yield Static("", id="adzuna_warn")

                    yield Checkbox("RemoteOK  (remote job feed)", id="remoteok_enabled")
                    yield Checkbox(
                        "LinkedIn  (browser scrape — needs chromium)",
                        id="linkedin_enabled",
                    )

            with Horizontal(classes="nav"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="continue", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        self.query_one("#greenhouse_enabled", Checkbox).value = s.greenhouse_enabled
        self.query_one("#gh_boards", TextArea).text = "\n".join(
            b["token"]
            if b["token"] == b.get("company")
            else f"{b['token']}, {b.get('company', '')}"
            for b in s.greenhouse_boards
        )
        self.query_one("#adzuna_enabled", Checkbox).value = s.adzuna_enabled
        self.query_one("#adzuna_country", Input).value = s.adzuna_country
        self.query_one("#remoteok_enabled", Checkbox).value = s.remoteok_enabled
        self.query_one("#linkedin_enabled", Checkbox).value = s.linkedin_enabled
        self._refresh_warning()

    def on_checkbox_changed(self, _: Checkbox.Changed) -> None:
        self._refresh_warning()

    def _refresh_warning(self) -> None:
        """Warn (don't block) if Adzuna is on but its API keys were left blank."""
        app: SetupApp = self.app  # type: ignore[assignment]
        warn = self.query_one("#adzuna_warn", Static)
        enabled = self.query_one("#adzuna_enabled", Checkbox).value
        if enabled and not (app.state.adzuna_app_id and app.state.adzuna_app_key):
            warn.update(
                "[yellow]⚠ Adzuna needs ADZUNA_APP_ID + ADZUNA_APP_KEY "
                "(set them on the Secrets screen) or its pulls will fail.[/yellow]"
            )
        else:
            warn.update("")

    def _save_to_state(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        s = app.state
        s.greenhouse_enabled = self.query_one("#greenhouse_enabled", Checkbox).value
        s.greenhouse_boards = parse_greenhouse_boards(
            self.query_one("#gh_boards", TextArea).text
        )
        s.adzuna_enabled = self.query_one("#adzuna_enabled", Checkbox).value
        s.adzuna_country = (
            self.query_one("#adzuna_country", Input).value.strip() or "us"
        )
        s.remoteok_enabled = self.query_one("#remoteok_enabled", Checkbox).value
        s.linkedin_enabled = self.query_one("#linkedin_enabled", Checkbox).value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "continue":
            self._save_to_state()
            self.app.push_screen(ConfirmScreen())


# Files atomic_write_all writes, in report order, with friendly labels for the plan.
_PLANNED_FILES = (
    (".env", "secrets"),
    ("config/profile_sources.yaml", "profile sources"),
    ("config/search.yaml", "search criteria"),
    ("config/connectors.yaml", "connectors"),
    ("config/review.yaml", "review roster (from example)"),
    ("config/review_deep.yaml", "deep review roster (from example)"),
    ("config/render.yaml", "render settings (from example)"),
)


class ConfirmScreen(Screen[None]):
    """Step 6 of 7 — show what will be written, then write atomically."""

    TITLE = "Resume Agent Setup  ·  6 / 7  ·  Confirm & write"

    CSS = """
    ConfirmScreen { align: center top; }
    ConfirmScreen #panel {
        width: 80;
        height: auto;
        border: round blue;
        padding: 1 2;
        margin-top: 2;
    }
    ConfirmScreen #status { height: 2; margin: 1 0; }
    ConfirmScreen #body   { height: 1fr; align: center top; }
    ConfirmScreen .nav    { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Ready to write configuration", id="heading")
                    yield DataTable(id="plan", show_cursor=False)
                    yield Static("Nothing has been written yet.", id="status")
            with Horizontal(classes="nav"):
                yield Button("← Back", id="back")
                yield Button("Write all config", id="write", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        table = self.query_one("#plan", DataTable)
        table.add_columns("File", "Action", "Contains")
        root = Path(app.root)
        for rel, desc in _PLANNED_FILES:
            action = "update" if (root / rel).exists() else "create"
            style = "yellow" if action == "update" else "green"
            table.add_row(rel, Text(action, style=style), desc)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "write":
            self._write()

    def _write(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        report = app._perform_write()
        errors = {p: s for p, s in report.items() if s != "written"}
        if errors:
            self.query_one("#status", Static).update(
                f"[bold red]✗ {len(errors)} file(s) failed — see handoff for details.[/bold red]"
            )
        else:
            self.query_one("#status", Static).update(
                "[bold green]✓ All files written.[/bold green]"
            )
        self.query_one("#write", Button).disabled = True
        self.app.push_screen(HandoffScreen())


class HandoffScreen(Screen[None]):
    """Step 7 of 7 — recap the write and show the exact next commands."""

    TITLE = "Resume Agent Setup  ·  7 / 7  ·  Done"

    CSS = """
    HandoffScreen { align: center top; }
    HandoffScreen #panel {
        width: 80;
        height: auto;
        border: round green;
        padding: 1 2;
        margin-top: 2;
    }
    HandoffScreen #report  { height: auto; margin-bottom: 1; }
    HandoffScreen #next     { height: auto; }
    HandoffScreen #body     { height: 1fr; align: center top; }
    HandoffScreen .nav      { height: 3; align-horizontal: right; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with VerticalScroll(id="body"):
                with Vertical(id="panel"):
                    yield Static("Setup complete", id="heading")
                    yield DataTable(id="report", show_cursor=False)
                    yield Static("", id="next")
            with Horizontal(classes="nav"):
                yield Button("Finish", id="finish", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        app: SetupApp = self.app  # type: ignore[assignment]
        table = self.query_one("#report", DataTable)
        table.add_columns("", "File")
        report = app.write_report or {}
        for path, status in report.items():
            ok = status == "written"
            icon = Text("✓", style="bold green") if ok else Text("✗", style="bold red")
            label = path if ok else f"{path} — {status}"
            table.add_row(icon, label)

        commands = []
        if app.state.resume_path:
            commands.append(
                "uv run resume-agent profile build   # extract facts from your resume"
            )
        commands.append(
            "uv run resume-agent discover            # run the discovery funnel"
        )
        commands.append(
            "make dev                                # open the web review board"
        )
        self.query_one("#next", Static).update(
            "[bold]Next steps:[/bold]\n\n  " + "\n  ".join(commands)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "finish":
            self.app.exit()
