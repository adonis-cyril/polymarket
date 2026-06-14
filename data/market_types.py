"""Shared types for cached Polymarket market records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_token_ids(raw: Any) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [str(token_id) for token_id in raw if token_id]


@dataclass
class ActiveMarketRecord:
    """Normalized active market row for cache + registry consumers."""

    condition_id: str
    event_id: str = ""
    event_slug: str = ""
    market_slug: str = ""
    question: str = ""
    outcomes: list[str] = field(default_factory=list)
    clob_token_ids: list[str] = field(default_factory=list)
    active: bool = True
    closed: bool = False
    end_date: Optional[datetime] = None
    volume_24hr: Optional[float] = None
    liquidity: Optional[float] = None
    gamma_updated_at: Optional[datetime] = None

    @classmethod
    def from_gamma_market(
        cls,
        market: dict[str, Any],
        *,
        event: Optional[dict[str, Any]] = None,
    ) -> Optional["ActiveMarketRecord"]:
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
        if not condition_id:
            return None

        event = event or {}
        outcomes = market.get("outcomes") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except json.JSONDecodeError:
                outcomes = []

        return cls(
            condition_id=condition_id,
            event_id=str(event.get("id") or market.get("event_id") or ""),
            event_slug=str(event.get("slug") or market.get("event_slug") or ""),
            market_slug=str(market.get("slug") or ""),
            question=str(market.get("question") or event.get("title") or ""),
            outcomes=[str(o) for o in outcomes],
            clob_token_ids=_parse_token_ids(market.get("clobTokenIds")),
            active=bool(market.get("active", True)),
            closed=bool(market.get("closed", False)),
            end_date=_parse_iso_dt(market.get("endDate") or event.get("endDate")),
            volume_24hr=_to_float(market.get("volume24hr") or event.get("volume24hr")),
            liquidity=_to_float(market.get("liquidity") or event.get("liquidity")),
            gamma_updated_at=_parse_iso_dt(market.get("updatedAt") or event.get("updatedAt")),
        )

    def to_db_row(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "event_id": self.event_id,
            "event_slug": self.event_slug,
            "market_slug": self.market_slug,
            "question": self.question,
            "outcomes": json.dumps(self.outcomes),
            "clob_token_ids": json.dumps(self.clob_token_ids),
            "active": self.active,
            "closed": self.closed,
            "end_date": self.end_date,
            "volume_24hr": self.volume_24hr,
            "liquidity": self.liquidity,
            "gamma_updated_at": self.gamma_updated_at,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ActiveMarketRecord":
        outcomes = row.get("outcomes") or []
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        token_ids = row.get("clob_token_ids") or []
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)

        return cls(
            condition_id=str(row["condition_id"]),
            event_id=str(row.get("event_id") or ""),
            event_slug=str(row.get("event_slug") or ""),
            market_slug=str(row.get("market_slug") or ""),
            question=str(row.get("question") or ""),
            outcomes=[str(o) for o in outcomes],
            clob_token_ids=[str(t) for t in token_ids],
            active=bool(row.get("active", True)),
            closed=bool(row.get("closed", False)),
            end_date=row.get("end_date"),
            volume_24hr=_to_float(row.get("volume_24hr")),
            liquidity=_to_float(row.get("liquidity")),
            gamma_updated_at=row.get("gamma_updated_at"),
        )


def flatten_gamma_events(events: list[dict[str, Any]]) -> list[ActiveMarketRecord]:
    """Expand Gamma /events payloads into per-market records."""
    records: list[ActiveMarketRecord] = []
    for event in events:
        for market in event.get("markets") or []:
            record = ActiveMarketRecord.from_gamma_market(market, event=event)
            if record and record.active and not record.closed:
                records.append(record)
    return records


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
