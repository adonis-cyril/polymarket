"""Main workstation layout — 2-pane Hummingbot design."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from terminal.commands.registry import CommandRegistry
from terminal.ui.widgets import (
    ActivityPane,
    CommandBar,
    LeftPane,
    MetricsBar,
    TopBar,
)


class WorkstationLayout(Vertical):
    """Two main windows + top/bottom bars."""

    DEFAULT_CSS = """
    WorkstationLayout {
        height: 100%;
    }
    #main-row {
        height: 1fr;
        min-height: 14;
    }
    #left-pane-wrap {
        width: 1fr;
        min-width: 28;
    }
    #right-pane-wrap {
        width: 1fr;
        min-width: 28;
    }
    .pane-header {
        height: 1;
        background: $surface;
        color: $secondary;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(id="workstation", **kwargs)
        self.registry = registry

    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")
        with Horizontal(id="main-row"):
            with Vertical(id="left-pane-wrap"):
                yield LeftPane(id="left-pane")
            with Vertical(id="right-pane-wrap"):
                yield ActivityPane(id="activity")
        yield MetricsBar(id="metrics-bar")
        yield CommandBar(self.registry, id="command-bar")
