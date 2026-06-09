"""Settings and config editor screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from terminal.commands.extended import get_config_manager


class SettingsScreen(Screen):
    """View and edit bot configuration."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("ctrl+s", "save", "Save"),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-panel {
        width: 90;
        height: auto;
        max-height: 90%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #config-table {
        height: 20;
        margin: 1 0;
    }
    #edit-row {
        height: 3;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            yield Static("[bold orange1]Configuration[/]", id="settings-title")
            yield Static("", id="config-summary")
            yield DataTable(id="config-table", zebra_stripes=True)
            yield Static("[dim]Select row, edit value below, Ctrl+S to save[/]")
            with Vertical(id="edit-row"):
                yield Input(placeholder="KEY=VALUE (e.g. BET_SIZE=1.00)", id="config-input")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#config-table", DataTable)
        table.add_columns("Group", "Key", "Value")
        self._load_config()
        self.query_one("#config-input", Input).focus()

    def _load_config(self) -> None:
        mgr = get_config_manager()
        self.query_one("#config-summary", Static).update(mgr.summary())
        table = self.query_one("#config-table", DataTable)
        table.clear()
        for entry in mgr.all_entries():
            table.add_row(entry.group, entry.key, entry.value)

    def action_save(self) -> None:
        text = self.query_one("#config-input", Input).value.strip()
        if "=" not in text:
            self.app._append_log("WARNING", "Use KEY=VALUE format", "config")  # type: ignore[attr-defined]
            return
        key, _, value = text.partition("=")
        msg = get_config_manager().set(key.strip(), value.strip())
        self.app._append_log("INFO", msg, "config")  # type: ignore[attr-defined]
        self.query_one("#config-input", Input).value = ""
        self._load_config()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        row_key = event.row_key
        if row_key is None:
            return
        try:
            key = str(table.get_row(row_key)[1])
            val = str(table.get_row(row_key)[2])
            self.query_one("#config-input", Input).value = f"{key}={val}"
        except Exception:
            pass

    def action_back(self) -> None:
        self.app.pop_screen()
