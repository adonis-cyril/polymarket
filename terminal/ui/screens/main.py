"""Primary trading screen — single 2-pane workstation."""

from __future__ import annotations

from textual.screen import Screen

from terminal.commands.registry import CommandRegistry
from terminal.ui.layout import WorkstationLayout


class MainScreen(Screen):
    """Hummingbot-inspired main view."""

    BINDINGS = [
        ("f5", "refresh", "Refresh"),
        ("ctrl+t", "toggle_activity", "Activity"),
        ("ctrl+s", "status", "Status"),
        ("?", "help", "Help"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registry = registry

    def compose(self):
        yield WorkstationLayout(self.registry)

    def action_refresh(self) -> None:
        self.app.refresh_data()  # type: ignore[attr-defined]

    def action_toggle_activity(self) -> None:
        self.query_one("#activity").focus()

    def action_status(self) -> None:
        self.run_worker(self.app.run_command("status"))  # type: ignore[attr-defined]

    def action_help(self) -> None:
        self.app.action_help()  # type: ignore[attr-defined]

    def action_quit_app(self) -> None:
        self.app.exit()
