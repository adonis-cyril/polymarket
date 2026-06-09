"""Password gate for the Polymarket terminal workstation."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from terminal.ui.widgets.welcome_art import POLYADONIS_BANNER

load_dotenv()

console = Console(stderr=True)

DEFAULT_MAX_ATTEMPTS = 3

LOGIN_STYLE = Style.from_dict(
    {
        "prompt": "bold #3b82f6",
        "input": "#e2e8f0",
        "hint": "italic #64748b",
    }
)


def get_admin_password() -> str:
    """Resolve admin password from env (dashboard + TUI share ADMIN_PASSWORD)."""
    return (
        os.getenv("TUI_ADMIN_PASSWORD", "").strip()
        or os.getenv("ADMIN_PASSWORD", "").strip()
    )


def validate_password(candidate: str, expected: str | None = None) -> bool:
    """Return True when candidate matches the configured admin password."""
    secret = expected if expected is not None else get_admin_password()
    if not secret:
        logger.warning("No ADMIN_PASSWORD configured — auth gate disabled")
        return True
    return candidate == secret


def _render_login_banner() -> None:
    body = Text()
    body.append(POLYADONIS_BANNER.strip("\n"), style="bold bright_blue")
    body.append("\n\n")
    body.append("Polymarket Trading Terminal\n", style="bold bright_white")
    body.append("Secure workstation access required\n", style="dim")
    panel = Panel(
        Align.center(body, vertical="middle"),
        border_style="bright_blue",
        title="[bold bright_blue]POLYADONIS[/]",
        subtitle="[dim]Ctrl+T toggle password visibility[/]",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def _prompt_password() -> str:
    show_password = {"value": False}
    bindings = KeyBindings()

    @bindings.add("c-t")
    def _toggle(event) -> None:
        show_password["value"] = not show_password["value"]
        event.app.invalidate()

    @Condition
    def _mask() -> bool:
        return not show_password["value"]

    session = PromptSession(
        style=LOGIN_STYLE,
        key_bindings=bindings,
    )
    return session.prompt(
        [("class:prompt", "Password "), ("class:hint", "(Ctrl+T show/hide) "), ("class:prompt", "› ")],
        is_password=_mask,
    )


def authenticate_interactive(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    expected: str | None = None,
) -> bool:
    """
    Prompt for masked password with retry limit and visibility toggle.

    Returns True on success. Exits the process on max failures or Ctrl+C.
    """
    secret = expected if expected is not None else get_admin_password()
    if not secret:
        console.print(
            "[yellow]Warning:[/] ADMIN_PASSWORD not set — skipping auth gate. "
            "Set ADMIN_PASSWORD in .env for production."
        )
        return True

    _render_login_banner()

    for attempt in range(1, max_attempts + 1):
        try:
            entered = _prompt_password()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled.[/]")
            sys.exit(130)

        if validate_password(entered, secret):
            console.print("[bold bright_blue]Access granted.[/] Launching workstation…\n")
            return True

        remaining = max_attempts - attempt
        if remaining <= 0:
            console.print("[red]Access denied.[/] Maximum attempts exceeded.")
            sys.exit(1)
        console.print(f"[red]Invalid password.[/] {remaining} attempt(s) remaining.\n")

    return False
