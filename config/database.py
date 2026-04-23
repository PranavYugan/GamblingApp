from __future__ import annotations

from typing import Any

import mysql.connector
from mysql.connector.connection import MySQLConnection

from config.environment import GLOBAL_CONTEXT, SqlEnvironmentContext


def _create_server_connection(context: SqlEnvironmentContext) -> MySQLConnection:
    return mysql.connector.connect(
        host=context.db_host,
        port=context.db_port,
        user=context.db_user,
        password=context.db_password,
    )


def ensure_database_exists(context: SqlEnvironmentContext | None = None) -> None:
    resolved = context or GLOBAL_CONTEXT
    connection = _create_server_connection(resolved)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{resolved.db_name}` CHARACTER SET {resolved.db_charset}"
            )
            connection.commit()
        finally:
            cursor.close()
    finally:
        connection.close()


def get_sql_connection(context: SqlEnvironmentContext | None = None) -> MySQLConnection:
    resolved = context or GLOBAL_CONTEXT
    ensure_database_exists(resolved)
    return mysql.connector.connect(
        host=resolved.db_host,
        port=resolved.db_port,
        user=resolved.db_user,
        password=resolved.db_password,
        database=resolved.db_name,
        autocommit=resolved.db_autocommit,
    )


def close_sql_connection(connection: Any) -> None:
    if connection is None:
        return
    try:
        connection.close()
    except Exception:
        pass
