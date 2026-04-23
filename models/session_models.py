from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _to_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


@dataclass(slots=True)
class SessionRecord:
    session_id: int | None
    gambler_id: int | None
    status: str
    end_reason: str | None
    starting_stake: Decimal
    ending_stake: Decimal
    peak_stake: Decimal
    lowest_stake: Decimal
    max_games: int
    games_played: int
    total_pause_seconds: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "SessionRecord":
        return cls(
            session_id=record.get("session_id"),
            gambler_id=record.get("gambler_id"),
            status=str(record.get("status", "")).strip().upper() or "UNKNOWN",
            end_reason=record.get("end_reason"),
            starting_stake=_to_decimal(record.get("starting_stake")),
            ending_stake=_to_decimal(record.get("ending_stake")),
            peak_stake=_to_decimal(record.get("peak_stake")),
            lowest_stake=_to_decimal(record.get("lowest_stake")),
            max_games=_to_int(record.get("max_games"), 0),
            games_played=_to_int(record.get("games_played"), 0),
            total_pause_seconds=_to_int(record.get("total_pause_seconds"), 0),
            started_at=_to_datetime(record.get("started_at")),
            ended_at=_to_datetime(record.get("ended_at")),
            created_at=_to_datetime(record.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "gambler_id": self.gambler_id,
            "status": self.status,
            "end_reason": self.end_reason,
            "starting_stake": self.starting_stake,
            "ending_stake": self.ending_stake,
            "peak_stake": self.peak_stake,
            "lowest_stake": self.lowest_stake,
            "max_games": self.max_games,
            "games_played": self.games_played,
            "total_pause_seconds": self.total_pause_seconds,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SessionParametersRecord:
    parameter_id: int | None
    session_id: int | None
    lower_limit: Decimal
    upper_limit: Decimal
    min_bet: Decimal
    max_bet: Decimal
    default_win_probability: Decimal
    max_session_minutes: int
    strict_mode: bool
    created_at: datetime | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "SessionParametersRecord":
        return cls(
            parameter_id=record.get("parameter_id"),
            session_id=record.get("session_id"),
            lower_limit=_to_decimal(record.get("lower_limit")),
            upper_limit=_to_decimal(record.get("upper_limit")),
            min_bet=_to_decimal(record.get("min_bet")),
            max_bet=_to_decimal(record.get("max_bet")),
            default_win_probability=_to_decimal(record.get("default_win_probability")),
            max_session_minutes=_to_int(record.get("max_session_minutes"), 120),
            strict_mode=_to_bool(record.get("strict_mode")),
            created_at=_to_datetime(record.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "session_id": self.session_id,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
            "min_bet": self.min_bet,
            "max_bet": self.max_bet,
            "default_win_probability": self.default_win_probability,
            "max_session_minutes": self.max_session_minutes,
            "strict_mode": self.strict_mode,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class PauseRecord:
    pause_id: int | None
    session_id: int | None
    pause_reason: str | None
    paused_at: datetime | None
    resumed_at: datetime | None
    pause_seconds: int | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "PauseRecord":
        raw_seconds = record.get("pause_seconds")
        return cls(
            pause_id=record.get("pause_id"),
            session_id=record.get("session_id"),
            pause_reason=record.get("pause_reason"),
            paused_at=_to_datetime(record.get("paused_at")),
            resumed_at=_to_datetime(record.get("resumed_at")),
            pause_seconds=None if raw_seconds is None else _to_int(raw_seconds, 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pause_id": self.pause_id,
            "session_id": self.session_id,
            "pause_reason": self.pause_reason,
            "paused_at": self.paused_at,
            "resumed_at": self.resumed_at,
            "pause_seconds": self.pause_seconds,
        }


@dataclass(slots=True)
class DurationMetrics:
    total_seconds: int
    paused_seconds: int
    active_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "paused_seconds": self.paused_seconds,
            "active_seconds": self.active_seconds,
            "total_minutes": Decimal(str(self.total_seconds / 60)).quantize(Decimal("0.01")),
            "paused_minutes": Decimal(str(self.paused_seconds / 60)).quantize(Decimal("0.01")),
            "active_minutes": Decimal(str(self.active_seconds / 60)).quantize(Decimal("0.01")),
        }
