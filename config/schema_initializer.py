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
    CREATE TABLE IF NOT EXISTS SESSIONS (
        session_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        gambler_id BIGINT UNSIGNED NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
        end_reason VARCHAR(40) NULL,
        starting_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        ending_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        peak_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        lowest_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        max_games INT NOT NULL DEFAULT 100,
        games_played INT NOT NULL DEFAULT 0,
        total_pause_seconds INT NOT NULL DEFAULT 0,
        started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ended_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (session_id),
        KEY idx_sessions_gambler_started (gambler_id, started_at),
        CONSTRAINT fk_sessions_gambler
            FOREIGN KEY (gambler_id)
            REFERENCES GAMBLERS (gambler_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS SESSION_PARAMETERS (
        parameter_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NOT NULL,
        lower_limit DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        upper_limit DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        min_bet DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        max_bet DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        default_win_probability DECIMAL(7, 6) NOT NULL DEFAULT 0.500000,
        max_session_minutes INT NOT NULL DEFAULT 120,
        strict_mode BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (parameter_id),
        UNIQUE KEY uq_session_parameters_session (session_id),
        CONSTRAINT fk_session_parameters_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS PAUSE_RECORDS (
        pause_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NOT NULL,
        pause_reason VARCHAR(255) NULL,
        paused_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resumed_at DATETIME NULL,
        pause_seconds INT NULL,
        PRIMARY KEY (pause_id),
        KEY idx_pause_records_session_paused (session_id, paused_at),
        CONSTRAINT fk_pause_records_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS BETTING_STRATEGIES (
        strategy_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
        strategy_code VARCHAR(40) NOT NULL,
        strategy_name VARCHAR(100) NOT NULL,
        strategy_type VARCHAR(40) NOT NULL,
        is_progressive BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (strategy_id),
        UNIQUE KEY uq_betting_strategies_code (strategy_code)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS BETS (
        bet_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NOT NULL,
        gambler_id BIGINT UNSIGNED NOT NULL,
        strategy_id SMALLINT UNSIGNED NOT NULL,
        game_index INT NOT NULL,
        bet_amount DECIMAL(18, 2) NOT NULL,
        win_probability DECIMAL(7, 6) NOT NULL DEFAULT 0.500000,
        odds_type VARCHAR(20) NOT NULL DEFAULT 'DECIMAL',
        odds_value DECIMAL(18, 6) NOT NULL DEFAULT 2.000000,
        potential_win DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        stake_before DECIMAL(18, 2) NOT NULL,
        stake_after DECIMAL(18, 2) NOT NULL,
        is_settled BOOLEAN NOT NULL DEFAULT FALSE,
        placed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (bet_id),
        UNIQUE KEY uq_bets_session_game_index (session_id, game_index),
        KEY idx_bets_session_placed (session_id, placed_at),
        KEY idx_bets_gambler_placed (gambler_id, placed_at),
        CONSTRAINT fk_bets_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        CONSTRAINT fk_bets_gambler
            FOREIGN KEY (gambler_id)
            REFERENCES GAMBLERS (gambler_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        CONSTRAINT fk_bets_strategy
            FOREIGN KEY (strategy_id)
            REFERENCES BETTING_STRATEGIES (strategy_id)
            ON DELETE RESTRICT
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS GAME_RECORDS (
        game_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NOT NULL,
        bet_id BIGINT UNSIGNED NOT NULL,
        outcome VARCHAR(20) NOT NULL,
        payout_amount DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        loss_amount DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        net_change DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        stake_before DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        stake_after DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        consecutive_win_streak INT NOT NULL DEFAULT 0,
        consecutive_loss_streak INT NOT NULL DEFAULT 0,
        game_duration_ms INT NULL,
        resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (game_id),
        UNIQUE KEY uq_game_records_bet (bet_id),
        KEY idx_game_records_session_resolved (session_id, resolved_at),
        CONSTRAINT fk_game_records_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        CONSTRAINT fk_game_records_bet
            FOREIGN KEY (bet_id)
            REFERENCES BETS (bet_id)
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
        KEY idx_stake_transactions_session_created (session_id, created_at),
        KEY idx_stake_transactions_gambler_created (gambler_id, created_at),
        CONSTRAINT fk_stake_transactions_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
            ON DELETE SET NULL
            ON UPDATE CASCADE,
        CONSTRAINT fk_stake_transactions_gambler
            FOREIGN KEY (gambler_id)
            REFERENCES GAMBLERS (gambler_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS RUNNING_TOTALS_SNAPSHOTS (
        snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        session_id BIGINT UNSIGNED NOT NULL,
        game_id BIGINT UNSIGNED NULL,
        total_games INT NOT NULL DEFAULT 0,
        transaction_count INT NOT NULL DEFAULT 0,
        total_credits DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        total_debits DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        net_change DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        current_balance DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        peak_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        lowest_stake DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
        volatility DECIMAL(18, 6) NOT NULL DEFAULT 0.000000,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (snapshot_id),
        KEY idx_running_snapshots_session_created (session_id, created_at),
        CONSTRAINT fk_running_snapshots_session
            FOREIGN KEY (session_id)
            REFERENCES SESSIONS (session_id)
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
