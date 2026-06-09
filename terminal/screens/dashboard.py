"""Main dashboard screen."""

from __future__ import annotations

from textual.screen import Screen

from terminal.commands.registry import CommandRegistry
from terminal.layouts import WorkstationLayout


class DashboardScreen(Screen):
    """Primary trading workstation view."""

    BINDINGS = [
        ("f5", "refresh", "Refresh"),
        ("ctrl+p", "command_palette", "Palette"),
        ("ctrl+l", "focus_logs", "Logs"),
        ("ctrl+t", "focus_trades", "Trades"),
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

    def action_command_palette(self) -> None:
        self.app.push_screen_command_palette()  # type: ignore[attr-defined]

    def action_focus_logs(self) -> None:
        self.query_one("#logs").focus()

    def action_focus_trades(self) -> None:
        self.query_one("#trades-table").focus()

    def action_help(self) -> None:
        self.app.push_screen_help()  # type: ignore[attr-defined]

    def action_quit_app(self) -> None:
        self.app.exit()
