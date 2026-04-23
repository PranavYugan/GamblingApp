from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _row_to_dict(row: Any, description: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    columns = [column[0] for column in description]
    return {columns[index]: row[index] for index in range(len(columns))}


class WinLossCalculator:
    def __init__(self, connection: Any):
        self.connection = connection
        self._ensure_default_odds_configurations()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_default_odds_configurations(self) -> None:
        defaults = (
            ("DECIMAL", Decimal("2.000000"), None, Decimal("2.000000"), Decimal("1.000000"), Decimal("0.000000"), 1),
            ("AMERICAN", Decimal("2.000000"), 100, Decimal("2.000000"), Decimal("1.000000"), Decimal("0.000000"), 0),
            ("PROBABILITY", Decimal("2.000000"), None, Decimal("2.000000"), Decimal("1.000000"), Decimal("0.000000"), 0),
        )
        cursor = self.connection.cursor()
        for odds_type, fixed_multiplier, american_odds, decimal_odds, probability_factor, house_edge, is_default in defaults:
            cursor.execute(
                """
                INSERT INTO ODDS_CONFIGURATIONS (
                    odds_type,
                    fixed_multiplier,
                    american_odds,
                    decimal_odds,
                    probability_payout_factor,
                    house_edge,
                    is_default,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    fixed_multiplier = VALUES(fixed_multiplier),
                    american_odds = VALUES(american_odds),
                    decimal_odds = VALUES(decimal_odds),
                    probability_payout_factor = VALUES(probability_payout_factor),
                    house_edge = VALUES(house_edge),
                    is_default = VALUES(is_default)
                """,
                (
                    odds_type,
                    str(fixed_multiplier),
                    american_odds,
                    str(decimal_odds),
                    str(probability_factor),
                    str(house_edge),
                    is_default,
                    self._utc_now(),
                ),
            )
        self.connection.commit()

    def _fetch_odds_configuration(self, odds_type: str) -> dict[str, Any]:
        resolved_type = (odds_type or "DECIMAL").strip().upper()
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                odds_config_id,
                odds_type,
                fixed_multiplier,
                american_odds,
                decimal_odds,
                probability_payout_factor,
                house_edge,
                is_default
            FROM ODDS_CONFIGURATIONS
            WHERE odds_type = %s
            LIMIT 1
            """,
            (resolved_type,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Odds configuration not found")
        return _row_to_dict(row, cursor.description)

    def _fetch_bet(self, bet_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                bet_id,
                session_id,
                gambler_id,
                game_index,
                bet_amount,
                win_probability,
                odds_type,
                odds_value,
                stake_after,
                is_settled
            FROM BETS
            WHERE bet_id = %s
            LIMIT 1
            """,
            (bet_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Bet not found")
        return _row_to_dict(row, cursor.description)

    def _resolve_decimal_odds(
        self,
        odds_type: str,
        odds_value: Decimal,
        win_probability: Decimal,
        configuration: Mapping[str, Any],
    ) -> Decimal:
        resolved_type = (odds_type or "DECIMAL").strip().upper()
        house_edge = _to_decimal(configuration.get("house_edge"))

        if resolved_type == "AMERICAN":
            american_raw = configuration.get("american_odds")
            american_odds = int(american_raw) if american_raw is not None else int(odds_value)
            if american_odds >= 0:
                decimal_odds = Decimal(american_odds) / Decimal("100") + Decimal("1")
            else:
                decimal_odds = Decimal("100") / abs(Decimal(american_odds)) + Decimal("1")
        elif resolved_type == "PROBABILITY":
            if win_probability <= 0:
                decimal_odds = Decimal("0")
            else:
                probability_factor = _to_decimal(configuration.get("probability_payout_factor"))
                decimal_odds = (Decimal("1") / win_probability) * probability_factor
        else:
            if odds_value > 0:
                decimal_odds = odds_value
            else:
                fallback = _to_decimal(configuration.get("decimal_odds"))
                decimal_odds = fallback if fallback > 0 else _to_decimal(configuration.get("fixed_multiplier"))

        if house_edge > 0 and house_edge < 1:
            decimal_odds = decimal_odds * (Decimal("1") - house_edge)

        if decimal_odds < 0:
            decimal_odds = Decimal("0")

        return decimal_odds

    def determine_outcome(
        self,
        win_probability: Any,
        forced_outcome: str | None = None,
        random_value: Any | None = None,
    ) -> str:
        if forced_outcome is not None:
            outcome = forced_outcome.strip().upper()
            if outcome not in {"WIN", "LOSS", "PUSH"}:
                raise ValueError("forced_outcome must be WIN, LOSS, or PUSH")
            return outcome

        probability = _to_decimal(win_probability)
        if probability < 0 or probability > 1:
            raise ValueError("win_probability must be between 0 and 1")

        if random_value is None:
            sample = Decimal(str(random.random()))
        else:
            sample = _to_decimal(random_value)

        if sample < 0 or sample > 1:
            raise ValueError("random_value must be between 0 and 1")

        return "WIN" if sample <= probability else "LOSS"

    def compute_payout_and_loss(
        self,
        bet_amount: Any,
        outcome: str,
        decimal_odds: Any,
    ) -> dict[str, Decimal]:
        amount = _money(_to_decimal(bet_amount))
        odds = _to_decimal(decimal_odds)
        resolved_outcome = outcome.strip().upper()

        if resolved_outcome == "WIN":
            payout = _money(amount * odds)
            loss = Decimal("0")
            settlement_amount = payout
            net_profit = _money(payout - amount)
        elif resolved_outcome == "PUSH":
            payout = amount
            loss = Decimal("0")
            settlement_amount = amount
            net_profit = Decimal("0")
        elif resolved_outcome == "LOSS":
            payout = Decimal("0")
            loss = amount
            settlement_amount = Decimal("0")
            net_profit = -amount
        else:
            raise ValueError("outcome must be WIN, LOSS, or PUSH")

        return {
            "payout_amount": payout,
            "loss_amount": loss,
            "settlement_amount": settlement_amount,
            "net_profit": _money(net_profit),
        }

    def _next_streak_values(self, session_id: int, outcome: str) -> tuple[int, int]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                outcome,
                consecutive_win_streak,
                consecutive_loss_streak
            FROM GAME_RECORDS
            WHERE session_id = %s
            ORDER BY resolved_at DESC, game_id DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            if outcome == "WIN":
                return 1, 0
            if outcome == "LOSS":
                return 0, 1
            return 0, 0

        data = _row_to_dict(row, cursor.description)
        previous_outcome = str(data.get("outcome") or "")
        previous_win = int(data.get("consecutive_win_streak") or 0)
        previous_loss = int(data.get("consecutive_loss_streak") or 0)

        if outcome == "WIN":
            return (previous_win + 1, 0) if previous_outcome == "WIN" else (1, 0)
        if outcome == "LOSS":
            return (0, previous_loss + 1) if previous_outcome == "LOSS" else (0, 1)
        return 0, 0

    def _upsert_game_record(
        self,
        bet: Mapping[str, Any],
        outcome: str,
        payout_amount: Decimal,
        loss_amount: Decimal,
        settlement_amount: Decimal,
        game_duration_ms: int | None,
    ) -> tuple[int, Decimal, Decimal]:
        bet_id = int(bet.get("bet_id"))
        session_id = int(bet.get("session_id"))

        cursor = self.connection.cursor()
        cursor.execute("SELECT game_id FROM GAME_RECORDS WHERE bet_id = %s LIMIT 1", (bet_id,))
        row = cursor.fetchone()

        stake_before = _money(_to_decimal(bet.get("stake_after")))
        stake_after = _money(stake_before + settlement_amount)
        win_streak, loss_streak = self._next_streak_values(session_id=session_id, outcome=outcome)
        resolved_at = self._utc_now()

        if row is None:
            cursor.execute(
                """
                INSERT INTO GAME_RECORDS (
                    session_id,
                    bet_id,
                    outcome,
                    payout_amount,
                    loss_amount,
                    net_change,
                    stake_before,
                    stake_after,
                    consecutive_win_streak,
                    consecutive_loss_streak,
                    game_duration_ms,
                    resolved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    bet_id,
                    outcome,
                    str(payout_amount),
                    str(loss_amount),
                    str(settlement_amount),
                    str(stake_before),
                    str(stake_after),
                    win_streak,
                    loss_streak,
                    game_duration_ms,
                    resolved_at,
                ),
            )
            game_id = cursor.lastrowid
            if game_id is None:
                self.connection.rollback()
                raise RuntimeError("Failed to insert game record")
        else:
            game_id = int(_row_to_dict(row, cursor.description).get("game_id") or row[0])
            cursor.execute(
                """
                UPDATE GAME_RECORDS
                SET
                    outcome = %s,
                    payout_amount = %s,
                    loss_amount = %s,
                    net_change = %s,
                    stake_before = %s,
                    stake_after = %s,
                    consecutive_win_streak = %s,
                    consecutive_loss_streak = %s,
                    game_duration_ms = %s,
                    resolved_at = %s
                WHERE game_id = %s
                """,
                (
                    outcome,
                    str(payout_amount),
                    str(loss_amount),
                    str(settlement_amount),
                    str(stake_before),
                    str(stake_after),
                    win_streak,
                    loss_streak,
                    game_duration_ms,
                    resolved_at,
                    game_id,
                ),
            )

        cursor.execute("UPDATE BETS SET is_settled = %s WHERE bet_id = %s", (1, bet_id))
        return int(game_id), stake_before, stake_after

    def _volatility_from_profits(self, profits: list[Decimal]) -> Decimal:
        if not profits:
            return Decimal("0")
        count = Decimal(len(profits))
        mean = sum(profits, Decimal("0")) / count
        variance = sum(((value - mean) ** 2 for value in profits), Decimal("0")) / count
        return variance.sqrt() if variance > 0 else Decimal("0")

    def calculate_win_loss_statistics(self, session_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_games,
                COALESCE(SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END), 0) AS total_wins,
                COALESCE(SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END), 0) AS total_losses,
                COALESCE(SUM(CASE WHEN outcome = 'PUSH' THEN 1 ELSE 0 END), 0) AS total_pushes,
                COALESCE(SUM(payout_amount), 0) AS total_payout,
                COALESCE(SUM(loss_amount), 0) AS total_loss_amount,
                COALESCE(SUM(net_change), 0) AS total_net_change,
                COALESCE(MAX(consecutive_win_streak), 0) AS longest_win_streak,
                COALESCE(MAX(consecutive_loss_streak), 0) AS longest_loss_streak,
                COALESCE(MAX(stake_after), 0) AS peak_stake,
                COALESCE(MIN(stake_after), 0) AS lowest_stake
            FROM GAME_RECORDS
            WHERE session_id = %s
            """,
            (session_id,),
        )
        aggregate_row = cursor.fetchone()
        aggregate = _row_to_dict(aggregate_row, cursor.description)

        cursor.execute(
            """
            SELECT COALESCE(SUM(b.bet_amount), 0) AS total_staked
            FROM BETS b
            INNER JOIN GAME_RECORDS gr ON gr.bet_id = b.bet_id
            WHERE b.session_id = %s
            """,
            (session_id,),
        )
        staked_row = cursor.fetchone()
        staked = _row_to_dict(staked_row, cursor.description)

        cursor.execute(
            """
            SELECT
                payout_amount,
                loss_amount
            FROM GAME_RECORDS
            WHERE session_id = %s
            ORDER BY resolved_at ASC, game_id ASC
            """,
            (session_id,),
        )
        profit_rows = cursor.fetchall() or []
        profits: list[Decimal] = []
        for row in profit_rows:
            data = _row_to_dict(row, cursor.description)
            profits.append(_to_decimal(data.get("payout_amount")) - _to_decimal(data.get("loss_amount")))

        total_games = int(aggregate.get("total_games") or 0)
        total_wins = int(aggregate.get("total_wins") or 0)
        total_losses = int(aggregate.get("total_losses") or 0)
        total_pushes = int(aggregate.get("total_pushes") or 0)
        total_payout = _money(_to_decimal(aggregate.get("total_payout")))
        total_loss_amount = _money(_to_decimal(aggregate.get("total_loss_amount")))
        total_staked = _money(_to_decimal(staked.get("total_staked")))
        net_profit = _money(total_payout - total_loss_amount)
        longest_win_streak = int(aggregate.get("longest_win_streak") or 0)
        longest_loss_streak = int(aggregate.get("longest_loss_streak") or 0)

        if total_losses > 0:
            win_loss_ratio: Decimal | None = (Decimal(total_wins) / Decimal(total_losses)).quantize(Decimal("0.0001"))
        else:
            win_loss_ratio = None

        if total_loss_amount > 0:
            profit_factor: Decimal | None = (total_payout / total_loss_amount).quantize(Decimal("0.0001"))
        else:
            profit_factor = None

        if total_staked > 0:
            roi_percent = ((net_profit / total_staked) * Decimal("100")).quantize(Decimal("0.01"))
        else:
            roi_percent = Decimal("0.00")

        if total_games > 0:
            win_rate_percent = ((Decimal(total_wins) / Decimal(total_games)) * Decimal("100")).quantize(Decimal("0.01"))
        else:
            win_rate_percent = Decimal("0.00")

        volatility = self._volatility_from_profits(profits).quantize(Decimal("0.0001"))

        return {
            "session_id": session_id,
            "total_games": total_games,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "total_pushes": total_pushes,
            "win_loss_ratio": win_loss_ratio,
            "win_rate_percent": win_rate_percent,
            "total_payout": total_payout,
            "total_loss_amount": total_loss_amount,
            "net_profit": net_profit,
            "total_staked": total_staked,
            "roi_percent": roi_percent,
            "profit_factor": profit_factor,
            "longest_win_streak": longest_win_streak,
            "longest_loss_streak": longest_loss_streak,
            "peak_stake": _money(_to_decimal(aggregate.get("peak_stake"))),
            "lowest_stake": _money(_to_decimal(aggregate.get("lowest_stake"))),
            "volatility": volatility,
        }

    def running_totals_by_game_index(self, session_id: int) -> list[dict[str, Any]]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                b.game_index,
                b.bet_id,
                b.bet_amount,
                gr.game_id,
                gr.outcome,
                gr.payout_amount,
                gr.loss_amount,
                gr.net_change,
                gr.stake_after,
                gr.resolved_at
            FROM GAME_RECORDS gr
            INNER JOIN BETS b ON b.bet_id = gr.bet_id
            WHERE gr.session_id = %s
            ORDER BY b.game_index ASC, gr.resolved_at ASC, gr.game_id ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall() or []
        running: list[dict[str, Any]] = []

        total_games = 0
        total_wins = 0
        total_losses = 0
        total_pushes = 0
        cumulative_payout = Decimal("0")
        cumulative_loss = Decimal("0")
        cumulative_staked = Decimal("0")

        for row in rows:
            data = _row_to_dict(row, cursor.description)
            total_games += 1

            outcome = str(data.get("outcome") or "").upper()
            if outcome == "WIN":
                total_wins += 1
            elif outcome == "LOSS":
                total_losses += 1
            else:
                total_pushes += 1

            payout = _money(_to_decimal(data.get("payout_amount")))
            loss = _money(_to_decimal(data.get("loss_amount")))
            bet_amount = _money(_to_decimal(data.get("bet_amount")))
            cumulative_payout += payout
            cumulative_loss += loss
            cumulative_staked += bet_amount
            net_profit = _money(cumulative_payout - cumulative_loss)

            if total_losses > 0:
                ratio: Decimal | None = (Decimal(total_wins) / Decimal(total_losses)).quantize(Decimal("0.0001"))
            else:
                ratio = None

            if cumulative_loss > 0:
                profit_factor: Decimal | None = (cumulative_payout / cumulative_loss).quantize(Decimal("0.0001"))
            else:
                profit_factor = None

            if cumulative_staked > 0:
                roi = ((net_profit / cumulative_staked) * Decimal("100")).quantize(Decimal("0.01"))
            else:
                roi = Decimal("0.00")

            running.append(
                {
                    "game_index": int(data.get("game_index") or 0),
                    "bet_id": int(data.get("bet_id") or 0),
                    "game_id": int(data.get("game_id") or 0),
                    "outcome": outcome,
                    "total_games": total_games,
                    "total_wins": total_wins,
                    "total_losses": total_losses,
                    "total_pushes": total_pushes,
                    "win_loss_ratio": ratio,
                    "cumulative_payout": _money(cumulative_payout),
                    "cumulative_loss": _money(cumulative_loss),
                    "cumulative_net_profit": net_profit,
                    "roi_percent": roi,
                    "profit_factor": profit_factor,
                    "stake_after": _money(_to_decimal(data.get("stake_after"))),
                    "resolved_at": data.get("resolved_at"),
                }
            )

        return running

    def _insert_running_snapshot(self, session_id: int, game_id: int | None = None) -> dict[str, Any]:
        running = self.running_totals_by_game_index(session_id)
        latest = running[-1] if running else None
        stats = self.calculate_win_loss_statistics(session_id)

        if latest is None:
            total_games = 0
            total_credits = Decimal("0")
            total_debits = Decimal("0")
            net_change = Decimal("0")
            current_balance = Decimal("0")
            peak_stake = Decimal("0")
            lowest_stake = Decimal("0")
        else:
            total_games = latest["total_games"]
            total_credits = latest["cumulative_payout"]
            total_debits = latest["cumulative_loss"]
            net_change = latest["cumulative_net_profit"]
            current_balance = latest["stake_after"]
            peak_stake = stats["peak_stake"]
            lowest_stake = stats["lowest_stake"]

        now = self._utc_now()
        cursor = self.connection.cursor()
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
                total_games,
                str(total_credits),
                str(total_debits),
                str(net_change),
                str(current_balance),
                str(peak_stake),
                str(lowest_stake),
                str(stats["volatility"]),
                now,
            ),
        )
        snapshot_id = cursor.lastrowid
        self.connection.commit()
        return {
            "snapshot_id": int(snapshot_id) if snapshot_id is not None else None,
            "session_id": session_id,
            "game_id": game_id,
            "created_at": now,
            "totals": latest,
            "statistics": stats,
        }

    def settle_game(
        self,
        bet_id: int,
        forced_outcome: str | None = None,
        random_value: Any | None = None,
        odds_type: str | None = None,
        odds_value: Any | None = None,
        game_duration_ms: int | None = None,
    ) -> dict[str, Any]:
        bet = self._fetch_bet(bet_id)
        if int(bet.get("is_settled") or 0) == 1:
            raise ValueError("Bet already settled")

        resolved_odds_type = (odds_type or str(bet.get("odds_type") or "DECIMAL")).strip().upper()
        configuration = self._fetch_odds_configuration(resolved_odds_type)
        probability = _to_decimal(bet.get("win_probability"))
        outcome = self.determine_outcome(
            win_probability=probability,
            forced_outcome=forced_outcome,
            random_value=random_value,
        )

        resolved_odds_value = _to_decimal(odds_value if odds_value is not None else bet.get("odds_value"))
        decimal_odds = self._resolve_decimal_odds(
            odds_type=resolved_odds_type,
            odds_value=resolved_odds_value,
            win_probability=probability,
            configuration=configuration,
        )

        settlement = self.compute_payout_and_loss(
            bet_amount=bet.get("bet_amount"),
            outcome=outcome,
            decimal_odds=decimal_odds,
        )

        game_id, stake_before, stake_after = self._upsert_game_record(
            bet=bet,
            outcome=outcome,
            payout_amount=settlement["payout_amount"],
            loss_amount=settlement["loss_amount"],
            settlement_amount=settlement["settlement_amount"],
            game_duration_ms=game_duration_ms,
        )

        snapshot = self._insert_running_snapshot(session_id=int(bet.get("session_id")), game_id=game_id)
        statistics = self.calculate_win_loss_statistics(int(bet.get("session_id")))

        return {
            "settlement_result": {
                "game_id": game_id,
                "bet_id": bet_id,
                "session_id": int(bet.get("session_id")),
                "outcome": outcome,
                "odds_type": resolved_odds_type,
                "decimal_odds_used": decimal_odds,
                "payout_amount": settlement["payout_amount"],
                "loss_amount": settlement["loss_amount"],
                "settlement_amount": settlement["settlement_amount"],
                "net_profit": settlement["net_profit"],
                "stake_before": stake_before,
                "stake_after": stake_after,
            },
            "statistics": statistics,
            "running_totals_snapshot": snapshot,
        }
