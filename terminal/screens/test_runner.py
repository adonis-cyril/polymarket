"""Live staircase test runner screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from terminal.commands.extended import get_test_runner


class TestRunnerScreen(Screen):
    """Run live staircase and operational checks."""

    BINDINGS = [
        ("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    TestRunnerScreen {
        align: center middle;
    }
    #test-panel {
        width: 85;
        height: auto;
        max-height: 90%;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #test-actions Button {
        margin: 0 1 1 0;
    }
    #test-output {
        height: 16;
        border: solid $border;
        overflow-y: auto;
        padding: 0 1;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="test-panel"):
            yield Static("[bold]Live Staircase & Checks[/]", id="test-title")
            yield Static(
                "[dim]Dry-run by default. Live orders require credentials + --live buttons.[/]",
            )
            with Horizontal(id="test-actions"):
                yield Button("Discover", id="btn-discover", variant="primary")
                yield Button("Account (live)", id="btn-account", variant="warning")
                yield Button("Status (live)", id="btn-status")
                yield Button("Buy (live)", id="btn-buy", variant="warning")
                yield Button("Preflight", id="btn-preflight")
                yield Button("Check Status", id="btn-check")
            yield Static("", id="test-output")
        yield Footer()

    async def _run_test(self, label: str, coro) -> None:
        self.query_one("#test-output", Static).update(f"Running {label}…")
        result = await coro
        preview = result.output[:3000]
        if len(result.output) > 3000:
            preview += "\n… (truncated)"
        status = "[green]OK[/]" if result.success else "[red]FAIL[/]"
        self.query_one("#test-output", Static).update(f"{status} {label}\n\n{preview}")
        self.app._append_log(  # type: ignore[attr-defined]
            "INFO" if result.success else "WARNING",
            f"{label}: exit {result.exit_code}",
            "tests",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        runner = get_test_runner()
        bid = event.button.id or ""

        if bid == "btn-discover":
            self.run_worker(self._run_test("discover", runner.run_staircase("discover")))
        elif bid == "btn-account":
            self.run_worker(self._run_test("account", runner.run_staircase("account", live=True)))
        elif bid == "btn-status":
            self.run_worker(self._run_test("status", runner.run_staircase("status", live=True)))
        elif bid == "btn-buy":
            self.run_worker(
                self._run_test("buy", runner.run_staircase("buy", live=True, side="up")),
            )
        elif bid == "btn-preflight":
            self.run_worker(self._run_test("preflight", runner.run_preflight(live=False)))
        elif bid == "btn-check":
            self.run_worker(self._run_test("check_status", runner.run_check_status(quick=True)))

    def action_back(self) -> None:
        self.app.pop_screen()
