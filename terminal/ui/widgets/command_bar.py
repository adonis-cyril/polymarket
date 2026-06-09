"""Command input bar with >>> prompt and short output zone."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static

from terminal.commands.registry import CommandRegistry
from terminal.ui.widgets.command_output import CommandOutput


class CommandSubmitted(Message):
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class CommandBar(Vertical):
    """Bottom command zone — Hummingbot-style >>> prompt + brief output."""

    DEFAULT_CSS = """
    CommandBar {
        height: auto;
        min-height: 11;
        max-height: 14;
        dock: bottom;
        background: $background;
        border-top: solid $border;
    }
    #command-input-row {
        height: 3;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
        background: $background;
    }
    CommandBar .prompt-label {
        color: $primary;
        text-style: bold;
        width: auto;
        padding-right: 1;
    }
    CommandBar Input {
        width: 1fr;
        border: none;
        background: transparent;
        color: $text;
    }
    CommandBar Input:focus {
        border: none;
        background: transparent;
    }
    #cmd-hint {
        height: 1;
        color: $text-muted;
        padding: 0 2;
        background: $surface;
    }
    """

    hint: reactive[str] = reactive("")

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registry = registry
        self._history: list[str] = []
        self._hist_idx = -1

    def compose(self) -> ComposeResult:
        with Horizontal(id="command-input-row"):
            yield Static(">>>", classes="prompt-label", id="prompt")
            yield Input(
                placeholder="run --strategy kelly | stop | connect | status | config | help",
                id="cmd-input",
            )
        yield Static("", id="cmd-hint")
        yield CommandOutput(id="cmd-output", markup=True, highlight=True, wrap=True)

    def on_mount(self) -> None:
        self.focus_input()

    def focus_input(self) -> None:
        try:
            self.query_one("#cmd-input", Input).focus()
        except Exception:
            pass

    def watch_hint(self, value: str) -> None:
        try:
            self.query_one("#cmd-hint", Static).update(value)
        except Exception:
            pass

    def show_output(self, message: str, level: str = "INFO") -> None:
        try:
            self.query_one("#cmd-output", CommandOutput).show_result(message, level)
        except Exception:
            pass

    def clear_output(self) -> None:
        try:
            self.query_one("#cmd-output", CommandOutput).clear_output()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "cmd-input":
            return
        text = event.value.strip()
        if not text:
            self.hint = ""
            return
        token = text.split()[0]
        matches = self.registry.autocomplete(token)
        if matches and matches[0] != token:
            self.hint = f"  → {', '.join(matches[:6])}"
        else:
            self.hint = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd-input":
            return
        cmd = event.value.strip()
        if cmd:
            self._history.append(cmd)
            self._hist_idx = len(self._history)
            self.post_message(CommandSubmitted(cmd))
        event.input.value = ""

    def action_history_up(self) -> None:
        if not self._history:
            return
        self._hist_idx = max(0, self._hist_idx - 1)
        self.query_one("#cmd-input", Input).value = self._history[self._hist_idx]

    def action_history_down(self) -> None:
        if not self._history:
            return
        self._hist_idx = min(len(self._history), self._hist_idx + 1)
        inp = self.query_one("#cmd-input", Input)
        inp.value = self._history[self._hist_idx] if self._hist_idx < len(self._history) else ""
