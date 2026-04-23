from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings


@dataclass(frozen=True, slots=True)
class SqlEnvironmentContext:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_charset: str
    db_autocommit: bool


def build_sql_environment_context() -> SqlEnvironmentContext:
    return SqlEnvironmentContext(
        db_host=settings.db_host,
        db_port=settings.db_port,
        db_name=settings.db_name,
        db_user=settings.db_user,
        db_password=settings.db_password,
        db_charset=settings.db_charset,
        db_autocommit=settings.db_autocommit,
    )


GLOBAL_CONTEXT = build_sql_environment_context()


def refresh_global_context() -> SqlEnvironmentContext:
    global GLOBAL_CONTEXT
    GLOBAL_CONTEXT = build_sql_environment_context()
    return GLOBAL_CONTEXT
