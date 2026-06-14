"""Thin Textual shell for the setup wizard.

The pure cores (state, yaml_gen, env_writer, preflight, validate, writer) hold
all logic. This App binds screens to a single WizardState and delegates writing
to an injected callable so the wiring is testable without a terminal.

Screen build-out follows the spec table (§5.2): Welcome/preflight, Secrets,
Profile sources, Search, Connectors, Confirm+write, Build profile, Handoff.
"""

from typing import Callable

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from resume_agent.setup.state import WizardState
from resume_agent.setup.writer import atomic_write_all


class SetupApp(App):
    """Wizard application. ``writer`` is injected for testability."""

    TITLE = "Resume Agent — Setup"

    def __init__(
        self,
        state: WizardState | None = None,
        writer: Callable[..., dict[str, str]] = atomic_write_all,
        root: str = ".",
    ) -> None:
        super().__init__()
        self.state = state or WizardState()
        self.writer = writer
        self.root = root
        self.write_report: dict[str, str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Welcome to Resume Agent setup.\n"
            "Press Ctrl+Q to quit. (Screens build out per spec §5.2.)",
            id="welcome",
        )
        yield Footer()

    def _perform_write(self) -> dict[str, str]:
        """Write all config from the current state. The atomic-at-end seam."""
        self.write_report = self.writer(self.state, root=self.root)
        return self.write_report
