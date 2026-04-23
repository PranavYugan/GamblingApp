from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import uuid4


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


def _row_to_dict(row: Any, description: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    columns = [column[0] for column in description]
    return {columns[index]: row[index] for index in range(len(columns))}


class StakeManagementService:
    def __init__(self, connection: Any):
        self.connection = connection

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _fetch_gambler(self, gambler_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                gambler_id,
                current_stake,
                win_threshold,
                loss_threshold,
                min_required_stake
            FROM GAMBLERS
            WHERE gambler_id = %s
            LIMIT 1
            """,
            (gambler_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Gambler profile not found")
        return _row_to_dict(row, cursor.description)

    def _fetch_session(self, session_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                session_id,
                gambler_id,
                status,
                end_reason,
                starting_stake,
                ending_stake,
                peak_stake,
                lowest_stake,
                max_games,
                games_played,
                started_at,
                ended_at,
                created_at
            FROM SESSIONS
            WHERE session_id = %s
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Session not found")
        return _row_to_dict(row, cursor.description)

    def initialize_session(
        self,
        gambler_id: int,
        max_games: int | None = None,
        starting_stake: Any | None = None,
    ) -> dict[str, Any]:
        gambler = self._fetch_gambler(gambler_id)
        start_stake = _to_decimal(starting_stake if starting_stake is not None else gambler.get("current_stake"))
        if start_stake < 0:
            raise ValueError("starting_stake must be non-negative")

        resolved_max_games = 100 if max_games is None else int(max_games)
        if resolved_max_games <= 0:
            raise ValueError("max_games must be a positive integer")

        now = self._utc_now()
        cursor = self.connection.cursor()

        cursor.execute(
            "UPDATE GAMBLERS SET current_stake = %s, updated_at = %s WHERE gambler_id = %s",
            (str(start_stake), now, gambler_id),
        )

        cursor.execute(
            """
            INSERT INTO SESSIONS (
                gambler_id,
                status,
                end_reason,
                starting_stake,
                ending_stake,
                peak_stake,
                lowest_stake,
                max_games,
                games_played,
                total_pause_seconds,
                started_at,
                ended_at,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                gambler_id,
                "ACTIVE",
                None,
                str(start_stake),
                str(start_stake),
                str(start_stake),
                str(start_stake),
                resolved_max_games,
                0,
                0,
                now,
                None,
                now,
            ),
        )

        session_id = cursor.lastrowid
        if session_id is None:
            self.connection.rollback()
            raise RuntimeError("Failed to create session")

        self._insert_snapshot(
            cursor=cursor,
            session_id=int(session_id),
            game_id=None,
            total_games=0,
            transaction_count=0,
            total_credits=Decimal("0"),
            total_debits=Decimal("0"),
            net_change=Decimal("0"),
            current_balance=start_stake,
            peak_stake=start_stake,
            lowest_stake=start_stake,
            volatility=Decimal("0"),
            created_at=now,
        )
        self.connection.commit()
        return self.get_real_time_balance(gambler_id=gambler_id, session_id=int(session_id))

    def _insert_snapshot(
        self,
        cursor: Any,
        session_id: int,
        game_id: int | None,
        total_games: int,
        transaction_count: int,
        total_credits: Decimal,
        total_debits: Decimal,
        net_change: Decimal,
        current_balance: Decimal,
        peak_stake: Decimal,
        lowest_stake: Decimal,
        volatility: Decimal,
        created_at: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO RUNNING_TOTALS_SNAPSHOTS (
                session_id,
                game_id,
                total_games,
                transaction_count,
                total_credits,
                total_debits,
                net_change,
                current_balance,
                peak_stake,
                lowest_stake,
                volatility,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                game_id,
                total_games,
                transaction_count,
                str(total_credits),
                str(total_debits),
                str(net_change),
                str(current_balance),
                str(peak_stake),
                str(lowest_stake),
                str(volatility),
                created_at,
            ),
        )

    def _generate_transaction_ref(self) -> str:
        return f"STK-{uuid4().hex}"

    def validate_boundaries(self, gambler_id: int, balance: Any | None = None) -> dict[str, Any]:
        gambler = self._fetch_gambler(gambler_id)
        current_balance = _to_decimal(balance if balance is not None else gambler.get("current_stake"))
        loss_threshold = _to_decimal(gambler.get("loss_threshold"))
        win_threshold = _to_decimal(gambler.get("win_threshold"))
        min_required_stake = _to_decimal(gambler.get("min_required_stake"))

        checks = {
            "non_negative_balance": current_balance >= 0,
            "meets_min_required_stake": current_balance >= min_required_stake,
            "above_loss_threshold": True if loss_threshold <= 0 else current_balance > loss_threshold,
            "below_win_threshold": True if win_threshold <= 0 else current_balance < win_threshold,
        }

        breaches: list[str] = []
        if not checks["non_negative_balance"]:
            breaches.append("negative_balance")
        if not checks["meets_min_required_stake"]:
            breaches.append("below_min_required_stake")
        if not checks["above_loss_threshold"]:
            breaches.append("loss_threshold_reached")
        if not checks["below_win_threshold"]:
            breaches.append("win_threshold_reached")

        return {
            "gambler_id": gambler_id,
            "balance": current_balance,
            "valid": len(breaches) == 0,
            "checks": checks,
            "breaches": breaches,
            "min_required_stake": min_required_stake,
            "loss_threshold": loss_threshold,
            "win_threshold": win_threshold,
        }

    def record_stake_transaction(
        self,
        session_id: int,
        gambler_id: int,
        transaction_type: str,
        amount: Any,
        bet_id: int | None = None,
        game_id: int | None = None,
        transaction_ref: str | None = None,
        increment_games: bool = False,
    ) -> dict[str, Any]:
        session = self._fetch_session(session_id)
        if _to_int(session.get("gambler_id")) != gambler_id:
            raise ValueError("Session gambler mismatch")

        gambler = self._fetch_gambler(gambler_id)
        balance_before = _to_decimal(gambler.get("current_stake"))
        amount_decimal = _to_decimal(amount)
        balance_after = balance_before + amount_decimal
        if balance_after < 0:
            raise ValueError("Transaction would result in negative balance")

        boundary_status = self.validate_boundaries(gambler_id=gambler_id, balance=balance_after)
        now = self._utc_now()
        current_peak = _to_decimal(session.get("peak_stake"))
        current_lowest = _to_decimal(session.get("lowest_stake"))
        peak_stake = max(current_peak, balance_after)
        lowest_stake = min(current_lowest, balance_after)
        games_played = _to_int(session.get("games_played")) + (1 if increment_games else 0)
        max_games = _to_int(session.get("max_games"), 100)
        status = str(session.get("status") or "ACTIVE")
        end_reason = session.get("end_reason")
        ended_at = session.get("ended_at")

        if status == "ACTIVE" and max_games > 0 and games_played >= max_games:
            status = "COMPLETED"
            end_reason = "MAX_GAMES_REACHED"
            ended_at = now

        if status == "ACTIVE" and not boundary_status["checks"]["above_loss_threshold"]:
            status = "COMPLETED"
            end_reason = "LOSS_THRESHOLD_REACHED"
            ended_at = now

        if status == "ACTIVE" and not boundary_status["checks"]["below_win_threshold"]:
            status = "COMPLETED"
            end_reason = "WIN_THRESHOLD_REACHED"
            ended_at = now

        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE GAMBLERS SET current_stake = %s, updated_at = %s WHERE gambler_id = %s",
            (str(balance_after), now, gambler_id),
        )
        cursor.execute(
            """
            UPDATE SESSIONS
            SET
                status = %s,
                end_reason = %s,
                ending_stake = %s,
                peak_stake = %s,
                lowest_stake = %s,
                games_played = %s,
                ended_at = %s
            WHERE session_id = %s
            """,
            (
                status,
                end_reason,
                str(balance_after),
                str(peak_stake),
                str(lowest_stake),
                games_played,
                ended_at,
                session_id,
            ),
        )
        resolved_ref = (transaction_ref or "").strip() or self._generate_transaction_ref()
        cursor.execute(
            """
            INSERT INTO STAKE_TRANSACTIONS (
                session_id,
                gambler_id,
                bet_id,
                game_id,
                transaction_type,
                amount,
                balance_before,
                balance_after,
                transaction_ref,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                gambler_id,
                bet_id,
                game_id,
                transaction_type,
                str(amount_decimal),
                str(balance_before),
                str(balance_after),
                resolved_ref,
                now,
            ),
        )

        summary = self.summarize_transactions(session_id)
        self._insert_snapshot(
            cursor=cursor,
            session_id=session_id,
            game_id=game_id,
            total_games=games_played,
            transaction_count=summary["transaction_count"],
            total_credits=summary["total_credits"],
            total_debits=summary["total_debits"],
            net_change=summary["net_change"],
            current_balance=balance_after,
            peak_stake=peak_stake,
            lowest_stake=lowest_stake,
            volatility=summary["volatility"],
            created_at=now,
        )
        self.connection.commit()

        return {
            "session_id": session_id,
            "gambler_id": gambler_id,
            "transaction_ref": resolved_ref,
            "transaction_type": transaction_type,
            "amount": amount_decimal,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "boundary_status": boundary_status,
            "real_time_balance": self.get_real_time_balance(gambler_id, session_id),
        }

    def get_stake_history(self, session_id: int, limit: int | None = 200) -> list[dict[str, Any]]:
        self._fetch_session(session_id)
        cursor = self.connection.cursor()
        if limit is None:
            cursor.execute(
                """
                SELECT
                    transaction_id,
                    session_id,
                    gambler_id,
                    bet_id,
                    game_id,
                    transaction_type,
                    amount,
                    balance_before,
                    balance_after,
                    transaction_ref,
                    created_at
                FROM STAKE_TRANSACTIONS
                WHERE session_id = %s
                ORDER BY created_at DESC, transaction_id DESC
                """,
                (session_id,),
            )
        else:
            resolved_limit = int(limit)
            if resolved_limit <= 0:
                raise ValueError("limit must be a positive integer")
            cursor.execute(
                """
                SELECT
                    transaction_id,
                    session_id,
                    gambler_id,
                    bet_id,
                    game_id,
                    transaction_type,
                    amount,
                    balance_before,
                    balance_after,
                    transaction_ref,
                    created_at
                FROM STAKE_TRANSACTIONS
                WHERE session_id = %s
                ORDER BY created_at DESC, transaction_id DESC
                LIMIT %s
                """,
                (session_id, resolved_limit),
            )

        rows = cursor.fetchall() or []
        results: list[dict[str, Any]] = []
        for row in rows:
            data = _row_to_dict(row, cursor.description)
            data["amount"] = _to_decimal(data.get("amount"))
            data["balance_before"] = _to_decimal(data.get("balance_before"))
            data["balance_after"] = _to_decimal(data.get("balance_after"))
            results.append(data)
        return results

    def summarize_transactions(self, session_id: int) -> dict[str, Any]:
        history = self.get_stake_history(session_id=session_id, limit=None)
        if not history:
            return {
                "session_id": session_id,
                "transaction_count": 0,
                "total_credits": Decimal("0"),
                "total_debits": Decimal("0"),
                "net_change": Decimal("0"),
                "average_change": Decimal("0"),
                "average_absolute_change": Decimal("0"),
                "volatility": Decimal("0"),
                "largest_credit": Decimal("0"),
                "largest_debit": Decimal("0"),
                "transaction_type_counts": {},
                "transaction_type_net": {},
            }

        amounts = [_to_decimal(row.get("amount")) for row in history]
        transaction_count = len(amounts)
        total_credits = sum((amount for amount in amounts if amount > 0), Decimal("0"))
        total_debits = sum((-amount for amount in amounts if amount < 0), Decimal("0"))
        net_change = sum(amounts, Decimal("0"))
        average_change = net_change / Decimal(transaction_count)
        absolute_changes = [abs(amount) for amount in amounts]
        average_absolute_change = sum(absolute_changes, Decimal("0")) / Decimal(transaction_count)
        variance = sum(((amount - average_change) ** 2 for amount in amounts), Decimal("0")) / Decimal(transaction_count)
        volatility = variance.sqrt() if variance > 0 else Decimal("0")
        largest_credit = max((amount for amount in amounts if amount > 0), default=Decimal("0"))
        largest_debit = min((amount for amount in amounts if amount < 0), default=Decimal("0"))

        transaction_type_counts: dict[str, int] = {}
        transaction_type_net: dict[str, Decimal] = {}
        for row in history:
            kind = str(row.get("transaction_type") or "UNKNOWN")
            amount = _to_decimal(row.get("amount"))
            transaction_type_counts[kind] = transaction_type_counts.get(kind, 0) + 1
            transaction_type_net[kind] = transaction_type_net.get(kind, Decimal("0")) + amount

        return {
            "session_id": session_id,
            "transaction_count": transaction_count,
            "total_credits": total_credits,
            "total_debits": total_debits,
            "net_change": net_change,
            "average_change": average_change,
            "average_absolute_change": average_absolute_change,
            "volatility": volatility,
            "largest_credit": largest_credit,
            "largest_debit": largest_debit,
            "transaction_type_counts": transaction_type_counts,
            "transaction_type_net": transaction_type_net,
        }

    def get_real_time_balance(self, gambler_id: int, session_id: int | None = None) -> dict[str, Any]:
        gambler = self._fetch_gambler(gambler_id)
        current_balance = _to_decimal(gambler.get("current_stake"))

        resolved_session: dict[str, Any] | None
        if session_id is not None:
            resolved_session = self._fetch_session(session_id)
            if _to_int(resolved_session.get("gambler_id")) != gambler_id:
                raise ValueError("Session gambler mismatch")
        else:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT
                    session_id,
                    gambler_id,
                    status,
                    end_reason,
                    starting_stake,
                    ending_stake,
                    peak_stake,
                    lowest_stake,
                    max_games,
                    games_played,
                    started_at,
                    ended_at,
                    created_at
                FROM SESSIONS
                WHERE gambler_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (gambler_id,),
            )
            row = cursor.fetchone()
            resolved_session = _row_to_dict(row, cursor.description) if row is not None else None

        if resolved_session is None:
            return {
                "gambler_id": gambler_id,
                "session_id": None,
                "current_balance": current_balance,
                "starting_stake": current_balance,
                "net_change_from_start": Decimal("0"),
                "peak_stake": current_balance,
                "lowest_stake": current_balance,
                "drawdown_from_peak": Decimal("0"),
                "recovery_from_low": Decimal("0"),
                "games_played": 0,
                "max_games": 0,
                "session_status": "NO_ACTIVE_SESSION",
                "started_at": None,
                "ended_at": None,
            }

        starting_stake = _to_decimal(resolved_session.get("starting_stake"))
        peak_stake = _to_decimal(resolved_session.get("peak_stake"))
        lowest_stake = _to_decimal(resolved_session.get("lowest_stake"))

        return {
            "gambler_id": gambler_id,
            "session_id": _to_int(resolved_session.get("session_id")),
            "current_balance": current_balance,
            "starting_stake": starting_stake,
            "net_change_from_start": current_balance - starting_stake,
            "peak_stake": peak_stake,
            "lowest_stake": lowest_stake,
            "drawdown_from_peak": peak_stake - current_balance,
            "recovery_from_low": current_balance - lowest_stake,
            "games_played": _to_int(resolved_session.get("games_played")),
            "max_games": _to_int(resolved_session.get("max_games")),
            "session_status": str(resolved_session.get("status") or "UNKNOWN"),
            "started_at": resolved_session.get("started_at"),
            "ended_at": resolved_session.get("ended_at"),
        }

    def get_peak_lowest_stake(self, session_id: int) -> dict[str, Any]:
        session = self._fetch_session(session_id)
        peak_stake = _to_decimal(session.get("peak_stake"))
        lowest_stake = _to_decimal(session.get("lowest_stake"))
        ending_stake = _to_decimal(session.get("ending_stake"))

        return {
            "session_id": session_id,
            "gambler_id": _to_int(session.get("gambler_id")),
            "peak_stake": peak_stake,
            "lowest_stake": lowest_stake,
            "stake_spread": peak_stake - lowest_stake,
            "current_balance": ending_stake,
            "distance_from_peak": peak_stake - ending_stake,
            "distance_from_lowest": ending_stake - lowest_stake,
            "session_status": str(session.get("status") or "UNKNOWN"),
        }

    def refresh_running_totals_snapshot(self, session_id: int, game_id: int | None = None) -> dict[str, Any]:
        session = self._fetch_session(session_id)
        now = self._utc_now()
        summary = self.summarize_transactions(session_id)

        cursor = self.connection.cursor()
        self._insert_snapshot(
            cursor=cursor,
            session_id=session_id,
            game_id=game_id,
            total_games=_to_int(session.get("games_played")),
            transaction_count=summary["transaction_count"],
            total_credits=summary["total_credits"],
            total_debits=summary["total_debits"],
            net_change=summary["net_change"],
            current_balance=_to_decimal(session.get("ending_stake")),
            peak_stake=_to_decimal(session.get("peak_stake")),
            lowest_stake=_to_decimal(session.get("lowest_stake")),
            volatility=summary["volatility"],
            created_at=now,
        )
        self.connection.commit()

        return {
            "session_id": session_id,
            "created_at": now,
            "summary": summary,
            "peak_lowest": self.get_peak_lowest_stake(session_id),
        }
