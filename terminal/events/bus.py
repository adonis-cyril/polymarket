"""Async event bus for decoupled TUI components."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, DefaultDict

from loguru import logger


class EventType(str, Enum):
    STATE_UPDATED = "state_updated"
    TRADES_UPDATED = "trades_updated"
    MARKETS_UPDATED = "markets_updated"
    POSITIONS_UPDATED = "positions_updated"
    CONNECTIVITY_UPDATED = "connectivity_updated"
    LEFT_VIEW_CHANGED = "left_view_changed"
    ACTIVITY_EVENT = "activity_event"
    LOG_MESSAGE = "log_message"
    NOTIFICATION = "notification"
    COMMAND_EXECUTED = "command_executed"
    THEME_CHANGED = "theme_changed"
    REFRESH_REQUESTED = "refresh_requested"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"


Handler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """Lightweight pub/sub for UI and service layers."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[EventType, list[Handler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        handlers = list(self._handlers.get(event.type, []))
        handlers.extend(self._handlers.get(EventType.__members__.get("_", event.type), []))
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.exception("Event handler error for {}: {}", event.type, exc)

    async def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        source: str = "system",
    ) -> None:
        await self.publish(Event(type=event_type, payload=payload or {}, source=source))
