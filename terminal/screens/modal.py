"""Modal screens — command palette, help."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from terminal.commands.registry import CommandRegistry


class CommandPaletteScreen(ModalScreen[str]):
    """Quick command launcher (Ctrl+P)."""

    DEFAULT_CSS = """
    CommandPaletteScreen {
        align: center middle;
    }
    #palette {
        width: 60;
        height: auto;
        max-height: 20;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registry = registry

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Static("[bold]Command Palette[/]", id="palette-title")
            yield Input(placeholder="Search commands…", id="palette-input")
            items = [
                ListItem(Label(f"{name}  [dim]{desc}[/]"))
                for name, (desc, _) in sorted(self.registry.commands.items())
            ]
            yield ListView(*items, id="palette-list")

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "palette-input":
            self.dismiss(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Label)
        cmd = str(label.renderable).split()[0]
        self.dismiss(cmd)


class HelpModal(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-box {
        width: 70;
        height: auto;
        max-height: 24;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registry = registry

    def compose(self) -> ComposeResult:
        lines = [
            "[bold bright_blue]Polymarket Terminal — Keyboard Shortcuts[/]",
            "",
            "  F2          Bot control (start/stop/pause)",
            "  F3          Test runner (staircase, preflight)",
            "  F4          Settings / config editor",
            "  F5          Force refresh",
            "  Ctrl+S      Run status command",
            "",
            "  run           List/start strategies (run --strategy kelly)",
            "  stop          Stop all running bots",
            "  connect       Link services + preflight",
            "  status        Health check",
            "  config        Bot settings",
            "  balance       USDC balance",
            "  Ctrl+P      Command palette",
            "  Ctrl+L      Focus logs",
            "  Ctrl+T      Focus trades table",
            "  /           Search trades",
            "  Ctrl+/      Search markets",
            "  ?           This help",
            "  q / Ctrl+Q  Quit",
            "",
            "[bold]Screens[/]",
            "  screen bot       Bot control panel",
            "  screen tests     Live staircase runner",
            "  screen settings  Config editor",
            "",
            "[bold]Commands[/]",
            self.registry.help_text(),
        ]
        with Vertical(id="help-box"):
            yield Static("\n".join(lines))

    def on_key(self, event) -> None:
        event.prevent_default()
        self.dismiss()
