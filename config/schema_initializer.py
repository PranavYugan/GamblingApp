from __future__ import annotations

from typing import Any

from config.database import get_sql_connection
from config.environment import SqlEnvironmentContext


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS GAMBLERS (
        gambler_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        username VARCHAR(80) NOT NULL,
        full_name VARCHAR(150) NOT NULL,
        email VARCHAR(255) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        initial_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        current_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        win_threshold DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        loss_threshold DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        min_required_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (gambler_id),
        UNIQUE KEY uq_gamblers_username (username),
        UNIQUE KEY uq_gamblers_email (email)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS BETTING_PREFERENCES (
        preference_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        gambler_id BIGINT UNSIGNED NOT NULL,
        min_bet DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        max_bet DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        preferred_game_type VARCHAR(80) NULL,
        auto_play_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        auto_play_max_games INT NULL,
        session_loss_limit DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        session_win_target DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (preference_id),
        UNIQUE KEY uq_betting_preferences_gambler (gambler_id),
        CONSTRAINT fk_betting_preferences_gambler
            FOREIGN KEY (gambler_id)
            REFERENCES GAMBLERS (gambler_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS STAKE_TRANSACTIONS (
        transaction_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NULL,
        gambler_id BIGINT UNSIGNED NOT NULL,
        bet_id BIGINT UNSIGNED NULL,
        game_id BIGINT UNSIGNED NULL,
        transaction_type VARCHAR(40) NOT NULL,
        amount DECIMAL(18, 2) NOT NULL,
        balance_before DECIMAL(18, 2) NOT NULL,
        balance_after DECIMAL(18, 2) NOT NULL,
        transaction_ref VARCHAR(120) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (transaction_id),
        UNIQUE KEY uq_stake_transactions_ref (transaction_ref),
        KEY idx_stake_transactions_gambler_created (gambler_id, created_at),
        CONSTRAINT fk_stake_transactions_gambler
            FOREIGN KEY (gambler_id)
            REFERENCES GAMBLERS (gambler_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
)


def initialize_schemas(connection: Any) -> None:
    cursor = connection.cursor()
    try:
        for statement in SCHEMA_STATEMENTS:
            cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close()


def initialize_database_and_schemas(context: SqlEnvironmentContext | None = None) -> Any:
    connection = get_sql_connection(context)
    initialize_schemas(connection)
    return connection
