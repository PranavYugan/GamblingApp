from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE, override=False)
else:
    load_dotenv(override=False)


def _read_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        if required:
            raise ValueError(f"{name} is required")
        return "" if default is None else default
    return value.strip()


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _to_int(name: str, value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _to_decimal(name: str, value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_env: str
    app_debug: bool
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_charset: str
    db_autocommit: bool
    session_default_win_probability: Decimal
    session_default_max_games: int
    session_default_max_minutes: int
    validation_strict_mode: bool
    min_initial_stake: Decimal
    max_initial_stake: Decimal

    @classmethod
    def from_env(cls) -> "Settings":
        app_name = _read_env("APP_NAME", "Gambling App")
        app_env = _read_env("APP_ENV", "dev")
        app_debug = _to_bool(_read_env("APP_DEBUG", "false"))
        db_host = _read_env("DB_HOST", required=True)
        db_port = _to_int("DB_PORT", _read_env("DB_PORT", "3306"))
        db_name = _read_env("DB_NAME", required=True)
        db_user = _read_env("DB_USER", required=True)
        db_password = _read_env("DB_PASSWORD", required=True)
        db_charset = _read_env("DB_CHARSET", "utf8mb4")
        db_autocommit = _to_bool(_read_env("DB_AUTOCOMMIT", "false"))
        session_default_win_probability = _to_decimal(
            "SESSION_DEFAULT_WIN_PROBABILITY",
            _read_env("SESSION_DEFAULT_WIN_PROBABILITY", "0.50"),
        )
        session_default_max_games = _to_int(
            "SESSION_DEFAULT_MAX_GAMES",
            _read_env("SESSION_DEFAULT_MAX_GAMES", "100"),
        )
        session_default_max_minutes = _to_int(
            "SESSION_DEFAULT_MAX_MINUTES",
            _read_env("SESSION_DEFAULT_MAX_MINUTES", "120"),
        )
        validation_strict_mode = _to_bool(_read_env("VALIDATION_STRICT_MODE", "true"))
        min_initial_stake = _to_decimal("MIN_INITIAL_STAKE", _read_env("MIN_INITIAL_STAKE", "100.00"))
        max_initial_stake = _to_decimal("MAX_INITIAL_STAKE", _read_env("MAX_INITIAL_STAKE", "1000000.00"))

        if session_default_win_probability < 0 or session_default_win_probability > 1:
            raise ValueError("SESSION_DEFAULT_WIN_PROBABILITY must be between 0 and 1")
        if session_default_max_games <= 0 or session_default_max_minutes <= 0:
            raise ValueError("Session defaults must be positive integers")
        if min_initial_stake < 0 or max_initial_stake < 0:
            raise ValueError("Stake values must be non-negative")
        if min_initial_stake > max_initial_stake:
            raise ValueError("MIN_INITIAL_STAKE must be <= MAX_INITIAL_STAKE")

        return cls(
            app_name=app_name,
            app_env=app_env,
            app_debug=app_debug,
            db_host=db_host,
            db_port=db_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            db_charset=db_charset,
            db_autocommit=db_autocommit,
            session_default_win_probability=session_default_win_probability,
            session_default_max_games=session_default_max_games,
            session_default_max_minutes=session_default_max_minutes,
            validation_strict_mode=validation_strict_mode,
            min_initial_stake=min_initial_stake,
            max_initial_stake=max_initial_stake,
        )


settings = Settings.from_env()

__all__ = ["Settings", "settings"]
