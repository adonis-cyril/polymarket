"""Command input bar with autocomplete hints."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static

from terminal.commands.registry import CommandRegistry


class CommandSubmitted(Message):
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class CommandBar(Static):
    """Bottom command line — prompt_toolkit-style UX in Textual."""

    DEFAULT_CSS = """
    CommandBar {
        height: 3;
        dock: bottom;
        layout: vertical;
    }
    CommandBar .prompt-label {
        color: $primary;
        text-style: bold;
        height: 1;
        padding: 0 1;
    }
    """

    hint: reactive[str] = reactive("")

    def __init__(self, registry: CommandRegistry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registry = registry
        self._history: list[str] = []
        self._hist_idx = -1

    def compose(self) -> ComposeResult:
        yield Static("poly> ", classes="prompt-label", id="prompt")
        yield Input(
            placeholder="Command: run --strategy kelly | stop | pause | config | help",
            id="cmd-input",
        )

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "cmd-input":
            return
        text = event.value.strip()
        if not text:
            self.hint = ""
            return
        matches = self.registry.autocomplete(text.split()[0])
        if matches and matches[0] != text.split()[0]:
            self.hint = f"  → {', '.join(matches[:5])}"
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
        inp = self.query_one("#cmd-input", Input)
        inp.value = self._history[self._hist_idx]

    def action_history_down(self) -> None:
        if not self._history:
            return
        self._hist_idx = min(len(self._history), self._hist_idx + 1)
        inp = self.query_one("#cmd-input", Input)
        inp.value = self._history[self._hist_idx] if self._hist_idx < len(self._history) else ""
