"""Main workstation layout — resizable panes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static

from terminal.commands.registry import CommandRegistry
from terminal.widgets import (
    ChartPane,
    CommandBar,
    LogPane,
    MetricsGrid,
    NotificationOverlay,
    SearchableDataTable,
    StatusBar,
)


class WorkstationLayout(Vertical):
    """Bloomberg-style multi-pane workstation."""

    DEFAULT_CSS = """
    WorkstationLayout {
        height: 100%;
    }
    #top-row {
        height: 1fr;
        min-height: 12;
    }
    #bottom-row {
        height: 1fr;
        min-height: 10;
    }
    #left-col {
        width: 1fr;
        min-width: 30;
    }
    #right-col {
        width: 1fr;
        min-width: 30;
    }
    .pane-container {
        height: 1fr;
        border: solid $border;
    }
    """

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(id="workstation", **kwargs)
        self.registry = registry

    def compose(self) -> ComposeResult:
        yield Static(
            " POLYMARKET TERMINAL  │  F2 Bot  F3 Tests  F4 Settings  │  Ctrl+P palette  F5 refresh",
            classes="header-bar",
        )
        yield NotificationOverlay(id="notifications")

        with Horizontal(id="top-row"):
            with Vertical(id="left-col"):
                yield Static(" METRICS ", classes="pane-title")
                yield MetricsGrid(id="metrics")
                yield Static(" EQUITY CURVE ", classes="pane-title")
                yield ChartPane(id="chart", title="Balance")

            with Vertical(id="right-col"):
                yield Static(" LIVE LOG ", classes="pane-title")
                yield LogPane(id="logs", markup=True, highlight=True)

        with Horizontal(id="bottom-row"):
            with Vertical(classes="pane-container"):
                yield Static(" RECENT TRADES ", classes="pane-title")
                yield SearchableDataTable(id="trades-table")

            with Vertical(classes="pane-container"):
                yield Static(" ACTIVE MARKETS ", classes="pane-title")
                yield SearchableDataTable(id="markets-table")

        yield StatusBar(id="status-bar")
        yield CommandBar(self.registry, id="command-bar")
        yield Footer()
