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


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


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
class BettingPreferences:
    preference_id: int | None
    gambler_id: int | None
    min_bet: Decimal
    max_bet: Decimal
    preferred_game_type: str | None
    auto_play_enabled: bool
    auto_play_max_games: int | None
    session_loss_limit: Decimal
    session_win_target: Decimal
    updated_at: datetime | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "BettingPreferences":
        return cls(
            preference_id=record.get("preference_id"),
            gambler_id=record.get("gambler_id"),
            min_bet=_to_decimal(record.get("min_bet")),
            max_bet=_to_decimal(record.get("max_bet")),
            preferred_game_type=record.get("preferred_game_type"),
            auto_play_enabled=_to_bool(record.get("auto_play_enabled")),
            auto_play_max_games=record.get("auto_play_max_games"),
            session_loss_limit=_to_decimal(record.get("session_loss_limit")),
            session_win_target=_to_decimal(record.get("session_win_target")),
            updated_at=_to_datetime(record.get("preferences_updated_at") or record.get("updated_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preference_id": self.preference_id,
            "gambler_id": self.gambler_id,
            "min_bet": self.min_bet,
            "max_bet": self.max_bet,
            "preferred_game_type": self.preferred_game_type,
            "auto_play_enabled": self.auto_play_enabled,
            "auto_play_max_games": self.auto_play_max_games,
            "session_loss_limit": self.session_loss_limit,
            "session_win_target": self.session_win_target,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class GamblerProfile:
    gambler_id: int | None
    username: str
    full_name: str
    email: str
    is_active: bool
    initial_stake: Decimal
    current_stake: Decimal
    win_threshold: Decimal
    loss_threshold: Decimal
    min_required_stake: Decimal
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "GamblerProfile":
        return cls(
            gambler_id=record.get("gambler_id"),
            username=str(record.get("username", "")).strip(),
            full_name=str(record.get("full_name", "")).strip(),
            email=str(record.get("email", "")).strip(),
            is_active=_to_bool(record.get("is_active")),
            initial_stake=_to_decimal(record.get("initial_stake")),
            current_stake=_to_decimal(record.get("current_stake")),
            win_threshold=_to_decimal(record.get("win_threshold")),
            loss_threshold=_to_decimal(record.get("loss_threshold")),
            min_required_stake=_to_decimal(record.get("min_required_stake")),
            created_at=_to_datetime(record.get("created_at")),
            updated_at=_to_datetime(record.get("updated_at")),
        )

    @property
    def net_profit(self) -> Decimal:
        return self.current_stake - self.initial_stake

    @property
    def roi_percent(self) -> Decimal:
        if self.initial_stake == 0:
            return Decimal("0")
        return (self.net_profit / self.initial_stake) * Decimal("100")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gambler_id": self.gambler_id,
            "username": self.username,
            "full_name": self.full_name,
            "email": self.email,
            "is_active": self.is_active,
            "initial_stake": self.initial_stake,
            "current_stake": self.current_stake,
            "win_threshold": self.win_threshold,
            "loss_threshold": self.loss_threshold,
            "min_required_stake": self.min_required_stake,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def current_financial_status(self) -> dict[str, Any]:
        available_to_bet = self.current_stake - self.min_required_stake
        if available_to_bet < 0:
            available_to_bet = Decimal("0")
        return {
            "gambler_id": self.gambler_id,
            "initial_stake": self.initial_stake,
            "current_stake": self.current_stake,
            "net_profit": self.net_profit,
            "roi_percent": self.roi_percent,
            "available_to_bet": available_to_bet,
            "distance_to_win_threshold": self.win_threshold - self.current_stake,
            "distance_to_loss_threshold": self.current_stake - self.loss_threshold,
        }

    def profile_summary(self, preferences: BettingPreferences | None = None) -> dict[str, Any]:
        summary = self.to_dict()
        summary["preferences"] = preferences.to_dict() if preferences else None
        return summary




















