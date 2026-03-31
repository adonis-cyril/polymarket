"""
Simple HTTP health check endpoint.

Runs on port 8080 so external monitors (cron, UptimeRobot, etc.)
can verify the bot is alive.

Usage:
    health_server = HealthServer(bot)
    await health_server.start()
    # ...
    await health_server.stop()
"""

import asyncio
import json
import logging
import time
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8080


class HealthServer:
    """Lightweight HTTP server for health checks."""

    def __init__(self, bot=None, port: int = DEFAULT_PORT):
        self.bot = bot
        self.port = port
        self._runner: Optional[web.AppRunner] = None
        self._start_time = time.time()

    async def start(self):
        """Start the health check server."""
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info("Health check server running on port %d", self.port)

    async def stop(self):
        """Stop the health check server."""
        if self._runner:
            await self._runner.cleanup()

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check request."""
        uptime = time.time() - self._start_time

        data = {
            "status": "ok",
            "uptime_seconds": int(uptime),
            "uptime_human": _format_duration(uptime),
        }

        if self.bot:
            data.update({
                "mode": "PAPER" if self.bot.paper_mode else "LIVE",
                "balance": round(self.bot.balance, 2),
                "total_trades": self.bot.total_trades,
                "win_rate": round(
                    self.bot.total_wins / self.bot.total_trades * 100, 1
                ) if self.bot.total_trades > 0 else 0,
                "consecutive_losses": self.bot.consecutive_losses,
                "current_level": self.bot.current_level,
                "binance_connected": self.bot.binance_ws.is_connected(),
                "polymarket_connected": self.bot.polymarket_ws.is_connected(),
            })

        return web.json_response(data)


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
