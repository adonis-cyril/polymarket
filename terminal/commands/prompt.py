"""prompt_toolkit integration for command input."""

from __future__ import annotations

from typing import Callable, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from terminal.commands.registry import CommandRegistry


class CommandCompleter(Completer):
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = text.split()[-1] if text else ""
        if " " not in text.strip():
            for name in self.registry.autocomplete(word):
                yield Completion(name, start_position=-len(word))


def build_prompt_session(
    registry: CommandRegistry,
    history_path: str = ".tui_history",
) -> PromptSession:
    kb = KeyBindings()

    @kb.add(Keys.ControlC)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt)

    @kb.add(Keys.ControlL)
    def _(event):
        event.app.renderer.clear()

    return PromptSession(
        completer=CommandCompleter(registry),
        history=FileHistory(history_path),
        key_bindings=kb,
        complete_while_typing=True,
    )


class CommandPromptSession:
    """Async-friendly wrapper around prompt_toolkit session."""

    def __init__(
        self,
        registry: CommandRegistry,
        on_submit: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.registry = registry
        self.on_submit = on_submit
        self._session = build_prompt_session(registry)
        self._history: list[str] = []

    @property
    def command_names(self) -> list[str]:
        return self.registry.names()

    def get_completions(self, prefix: str) -> list[str]:
        return self.registry.autocomplete(prefix)

    def add_to_history(self, line: str) -> None:
        if line and (not self._history or self._history[-1] != line):
            self._history.append(line)
            if len(self._history) > 200:
                self._history = self._history[-200:]

    def history_up(self) -> Optional[str]:
        return self._history[-1] if self._history else None
