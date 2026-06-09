"""POLYADONIS welcome banner — blue-on-black startup screen."""

from __future__ import annotations

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

POLYADONIS_BANNER = r"""
 ██████╗  ██████╗ ██╗  ██╗   ██╗ █████╗ ██████╗  ██████╗ ███╗   ██╗██╗███████╗
 ██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝██╔══██╗██╔══██╗██╔═══██╗████╗  ██║██║██╔════╝
 ██████╔╝██║   ██║██║   ╚████╔╝ ███████║██║  ██║██║   ██║██╔██╗ ██║██║███████╗
 ██╔═══╝ ██║   ██║██║    ╚██╔╝  ██╔══██║██║  ██║██║   ██║██║╚██╗██║██║╚════██║
 ██║     ╚██████╔╝███████╗██║   ██║  ██║██████╔╝╚██████╔╝██║ ╚████║██║███████║
 ╚═╝      ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═╝╚══════╝
"""

WELCOME_HINTS = [
    "Type connect to link services and run preflight",
    "run      list/start strategies (run --strategy kelly)",
    "stop     stop all running bots",
    "status   health check (Gamma, CLOB, DB, bot)",
    "config   view bets and bot settings",
    "balance  fetch live USDC balance",
    "help     full command list",
]


def build_welcome_panel() -> Panel:
    """Render the default left-pane welcome screen."""
    body = Text()
    body.append(POLYADONIS_BANNER.strip("\n"), style="bold bright_blue")
    body.append("\n\n")
    body.append("Polymarket Trading Terminal\n", style="bold bright_white")
    body.append("─────────────────────────────\n", style="dim")
    for hint in WELCOME_HINTS:
        cmd, _, desc = hint.partition("  ")
        body.append(f"  {cmd:<10}", style="bold bright_blue")
        body.append(f" {desc}\n", style="dim")
    return Panel(
        Align.center(body, vertical="middle"),
        border_style="bright_blue",
        title="[bold bright_blue]Welcome[/]",
        subtitle="[dim]not connected — run connect[/]",
    )
