from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from .stake_management_service import StakeManagementService
from strategies import FixedStakeStrategy, MartingaleStrategy, PercentageStakeStrategy


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


class BettingService:
    def __init__(self, connection: Any, stake_management_service: StakeManagementService | None = None):
        self.connection = connection
        self.stake_management_service = stake_management_service or StakeManagementService(connection)
        self._strategies = {
            "FIXED": FixedStakeStrategy(),
            "MARTINGALE": MartingaleStrategy(),
            "PERCENTAGE": PercentageStakeStrategy(),
        }
        self._ensure_default_strategies()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_default_strategies(self) -> None:
        defaults = (
            ("FIXED", "Fixed Stake", "FLAT", 0, 1),
            ("MARTINGALE", "Martingale", "PROGRESSION", 1, 1),
            ("PERCENTAGE", "Percentage Stake", "PERCENTAGE", 0, 1),
        )
        cursor = self.connection.cursor()
        for strategy_code, strategy_name, strategy_type, is_progressive, is_active in defaults:
            cursor.execute(
                """
                INSERT INTO BETTING_STRATEGIES (
                    strategy_code,
                    strategy_name,
                    strategy_type,
                    is_progressive,
                    is_active,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    strategy_name = VALUES(strategy_name),
                    strategy_type = VALUES(strategy_type),
                    is_progressive = VALUES(is_progressive),
                    is_active = VALUES(is_active)
                """,
                (
                    strategy_code,
                    strategy_name,
                    strategy_type,
                    is_progressive,
                    is_active,
                    self._utc_now(),
                ),
            )
        self.connection.commit()

    def _fetch_gambler(self, gambler_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                gambler_id,
                is_active,
                current_stake,
                min_required_stake,
                win_threshold,
                loss_threshold
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
                max_games,
                games_played
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

    def _fetch_strategy(self, strategy_code: str) -> dict[str, Any]:
        code = strategy_code.strip().upper()
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                strategy_id,
                strategy_code,
                strategy_name,
                strategy_type,
                is_progressive,
                is_active
            FROM BETTING_STRATEGIES
            WHERE strategy_code = %s
            LIMIT 1
            """,
            (code,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Betting strategy not found")
        strategy = _row_to_dict(row, cursor.description)
        if int(strategy.get("is_active") or 0) == 0:
            raise ValueError("Betting strategy is inactive")
        return strategy

    def _fetch_preferences(self, gambler_id: int) -> dict[str, Any] | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                min_bet,
                max_bet
            FROM BETTING_PREFERENCES
            WHERE gambler_id = %s
            LIMIT 1
            """,
            (gambler_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, cursor.description)

    def _fetch_last_settled_bet(self, session_id: int) -> tuple[Decimal | None, str | None]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                b.bet_amount,
                gr.outcome
            FROM GAME_RECORDS gr
            INNER JOIN BETS b ON b.bet_id = gr.bet_id
            WHERE gr.session_id = %s
            ORDER BY gr.resolved_at DESC, gr.game_id DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None, None
        data = _row_to_dict(row, cursor.description)
        return _to_decimal(data.get("bet_amount")), str(data.get("outcome") or "")

    def _next_game_index(self, session_id: int) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(game_index), 0) + 1 AS next_game_index FROM BETS WHERE session_id = %s",
            (session_id,),
        )
        row = cursor.fetchone()
        data = _row_to_dict(row, cursor.description)
        return int(data.get("next_game_index") or 1)

    def _validate_session_for_bet(self, session_id: int, gambler_id: int) -> dict[str, Any]:
        session = self._fetch_session(session_id)
        if int(session.get("gambler_id") or 0) != gambler_id:
            raise ValueError("Session gambler mismatch")
        status = str(session.get("status") or "").upper()
        if status != "ACTIVE":
            raise ValueError("Session is not active")
        max_games = int(session.get("max_games") or 0)
        games_played = int(session.get("games_played") or 0)
        if max_games > 0 and games_played >= max_games:
            raise ValueError("Session max games reached")
        return session

    def _resolve_strategy_bet_amount(
        self,
        strategy_code: str,
        current_stake: Decimal,
        requested_amount: Decimal | None,
        session_id: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> Decimal:
        code = strategy_code.strip().upper()
        strategy = self._strategies.get(code)
        if strategy is None:
            raise ValueError(f"Unsupported strategy code: {strategy_code}")
        last_bet_amount, last_outcome = self._fetch_last_settled_bet(session_id)
        amount = strategy.propose_bet_amount(
            current_stake=current_stake,
            requested_amount=requested_amount,
            last_bet_amount=last_bet_amount,
            last_outcome=last_outcome,
            metadata=metadata,
        )
        return _money(_to_decimal(amount))

    def validate_bet_amount(self, session_id: int, gambler_id: int, bet_amount: Any) -> dict[str, Any]:
        self._validate_session_for_bet(session_id, gambler_id)
        gambler = self._fetch_gambler(gambler_id)
        preferences = self._fetch_preferences(gambler_id)
        amount = _money(_to_decimal(bet_amount))
        current_stake = _to_decimal(gambler.get("current_stake"))
        min_required_stake = _to_decimal(gambler.get("min_required_stake"))

        min_bet = Decimal("0")
        max_bet = Decimal("0")
        if preferences is not None:
            min_bet = _to_decimal(preferences.get("min_bet"))
            max_bet = _to_decimal(preferences.get("max_bet"))

        checks = {
            "gambler_active": int(gambler.get("is_active") or 0) == 1,
            "bet_positive": amount > 0,
            "bet_within_current_stake": amount <= current_stake,
            "post_bet_above_min_required_stake": (current_stake - amount) >= min_required_stake,
            "meets_preference_min_bet": True if min_bet <= 0 else amount >= min_bet,
            "within_preference_max_bet": True if max_bet <= 0 else amount <= max_bet,
        }

        reasons: list[str] = []
        if not checks["gambler_active"]:
            reasons.append("account_inactive")
        if not checks["bet_positive"]:
            reasons.append("invalid_bet_amount")
        if not checks["bet_within_current_stake"]:
            reasons.append("bet_exceeds_current_stake")
        if not checks["post_bet_above_min_required_stake"]:
            reasons.append("bet_breaks_min_required_stake")
        if not checks["meets_preference_min_bet"]:
            reasons.append("bet_below_preference_min_bet")
        if not checks["within_preference_max_bet"]:
            reasons.append("bet_above_preference_max_bet")

        return {
            "session_id": session_id,
            "gambler_id": gambler_id,
            "bet_amount": amount,
            "valid": len(reasons) == 0,
            "reasons": reasons,
            "checks": checks,
            "bounds": {
                "current_stake": current_stake,
                "min_required_stake": min_required_stake,
                "min_bet": min_bet,
                "max_bet": max_bet,
            },
        }

    def _calculate_potential_win(
        self,
        bet_amount: Decimal,
        odds_type: str,
        odds_value: Decimal,
        win_probability: Decimal,
    ) -> Decimal:
        resolved_type = odds_type.strip().upper()
        if resolved_type == "PROBABILITY":
            if win_probability <= 0:
                return Decimal("0")
            factor = Decimal("1") / win_probability
            return _money(bet_amount * factor)
        return _money(bet_amount * odds_value)

    def place_single_bet(
        self,
        session_id: int,
        gambler_id: int,
        bet_amount: Any | None,
        strategy_code: str = "FIXED",
        win_probability: Any = Decimal("0.50"),
        odds_type: str = "DECIMAL",
        odds_value: Any = Decimal("2.0"),
        strategy_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_session_for_bet(session_id, gambler_id)
        strategy = self._fetch_strategy(strategy_code)
        gambler = self._fetch_gambler(gambler_id)
        current_stake = _money(_to_decimal(gambler.get("current_stake")))
        requested_amount = None if bet_amount is None else _money(_to_decimal(bet_amount))
        resolved_bet_amount = self._resolve_strategy_bet_amount(
            strategy_code=str(strategy.get("strategy_code") or strategy_code),
            current_stake=current_stake,
            requested_amount=requested_amount,
            session_id=session_id,
            metadata=strategy_metadata,
        )

        validation = self.validate_bet_amount(
            session_id=session_id,
            gambler_id=gambler_id,
            bet_amount=resolved_bet_amount,
        )
        if not validation["valid"]:
            raise ValueError("; ".join(validation["reasons"]))

        resolved_win_probability = _to_decimal(win_probability)
        if resolved_win_probability < 0 or resolved_win_probability > 1:
            raise ValueError("win_probability must be between 0 and 1")

        resolved_odds_type = odds_type.strip().upper() if odds_type else "DECIMAL"
        resolved_odds_value = _to_decimal(odds_value)
        if resolved_odds_value <= 0:
            raise ValueError("odds_value must be positive")

        game_index = self._next_game_index(session_id)
        stake_before = current_stake
        stake_after = _money(stake_before - resolved_bet_amount)
        potential_win = self._calculate_potential_win(
            bet_amount=resolved_bet_amount,
            odds_type=resolved_odds_type,
            odds_value=resolved_odds_value,
            win_probability=resolved_win_probability,
        )

        now = self._utc_now()
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO BETS (
                    session_id,
                    gambler_id,
                    strategy_id,
                    game_index,
                    bet_amount,
                    win_probability,
                    odds_type,
                    odds_value,
                    potential_win,
                    stake_before,
                    stake_after,
                    is_settled,
                    placed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    gambler_id,
                    int(strategy.get("strategy_id")),
                    game_index,
                    str(resolved_bet_amount),
                    str(resolved_win_probability),
                    resolved_odds_type,
                    str(resolved_odds_value),
                    str(potential_win),
                    str(stake_before),
                    str(stake_after),
                    0,
                    now,
                ),
            )
            bet_id = cursor.lastrowid
            if bet_id is None:
                self.connection.rollback()
                raise RuntimeError("Failed to create bet")

            stake_update = self.stake_management_service.record_stake_transaction(
                session_id=session_id,
                gambler_id=gambler_id,
                transaction_type="BET_PLACED",
                amount=-resolved_bet_amount,
                bet_id=int(bet_id),
                game_id=None,
                increment_games=False,
            )
        except Exception:
            self.connection.rollback()
            raise

        return {
            "bet_confirmation": {
                "bet_id": int(bet_id),
                "session_id": session_id,
                "gambler_id": gambler_id,
                "strategy_code": str(strategy.get("strategy_code")),
                "game_index": game_index,
                "bet_amount": resolved_bet_amount,
                "win_probability": resolved_win_probability,
                "odds_type": resolved_odds_type,
                "odds_value": resolved_odds_value,
                "potential_win": potential_win,
                "stake_before": stake_update["balance_before"],
                "stake_after": stake_update["balance_after"],
                "transaction_ref": stake_update["transaction_ref"],
                "placed_at": now,
            },
            "updated_stake_values": stake_update["real_time_balance"],
        }

    def place_multiple_bets(
        self,
        session_id: int,
        gambler_id: int,
        bets: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        confirmations: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for index, spec in enumerate(bets):
            try:
                result = self.place_single_bet(
                    session_id=session_id,
                    gambler_id=gambler_id,
                    bet_amount=spec.get("bet_amount"),
                    strategy_code=str(spec.get("strategy_code", "FIXED")),
                    win_probability=spec.get("win_probability", Decimal("0.50")),
                    odds_type=str(spec.get("odds_type", "DECIMAL")),
                    odds_value=spec.get("odds_value", Decimal("2.0")),
                    strategy_metadata=spec.get("strategy_metadata"),
                )
                confirmations.append(result["bet_confirmation"])
            except Exception as exc:
                failures.append(
                    {
                        "index": index,
                        "error": str(exc),
                        "input": dict(spec),
                    }
                )

        return {
            "session_id": session_id,
            "gambler_id": gambler_id,
            "bet_confirmations": confirmations,
            "failed_bets": failures,
            "updated_stake_values": self.stake_management_service.get_real_time_balance(
                gambler_id=gambler_id,
                session_id=session_id,
            ),
        }

    def _fetch_open_bet(self, bet_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                bet_id,
                session_id,
                gambler_id,
                bet_amount,
                potential_win,
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
        data = _row_to_dict(row, cursor.description)
        if int(data.get("is_settled") or 0) == 1:
            raise ValueError("Bet already settled")
        return data

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

    def resolve_bet(
        self,
        bet_id: int,
        outcome: str,
        payout_amount: Any | None = None,
        game_duration_ms: int | None = None,
    ) -> dict[str, Any]:
        bet = self._fetch_open_bet(bet_id)
        session_id = int(bet.get("session_id"))
        gambler_id = int(bet.get("gambler_id"))
        bet_amount = _money(_to_decimal(bet.get("bet_amount")))
        potential_win = _money(_to_decimal(bet.get("potential_win")))

        resolved_outcome = str(outcome or "").strip().upper()
        if resolved_outcome not in {"WIN", "LOSS", "PUSH"}:
            raise ValueError("outcome must be WIN, LOSS, or PUSH")

        if resolved_outcome == "WIN":
            settlement_amount = _money(_to_decimal(payout_amount if payout_amount is not None else potential_win))
            payout = settlement_amount
            loss = Decimal("0")
            transaction_type = "BET_SETTLED_WIN"
        elif resolved_outcome == "PUSH":
            settlement_amount = _money(_to_decimal(payout_amount if payout_amount is not None else bet_amount))
            payout = settlement_amount
            loss = Decimal("0")
            transaction_type = "BET_SETTLED_PUSH"
        else:
            settlement_amount = Decimal("0")
            payout = Decimal("0")
            loss = bet_amount
            transaction_type = "BET_SETTLED_LOSS"

        gambler = self._fetch_gambler(gambler_id)
        stake_before = _money(_to_decimal(gambler.get("current_stake")))
        stake_after = _money(stake_before + settlement_amount)
        win_streak, loss_streak = self._next_streak_values(session_id=session_id, outcome=resolved_outcome)
        now = self._utc_now()

        cursor = self.connection.cursor()
        try:
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
                    resolved_outcome,
                    str(payout),
                    str(loss),
                    str(settlement_amount),
                    str(stake_before),
                    str(stake_after),
                    win_streak,
                    loss_streak,
                    game_duration_ms,
                    now,
                ),
            )
            game_id = cursor.lastrowid
            if game_id is None:
                self.connection.rollback()
                raise RuntimeError("Failed to create game record")

            cursor.execute("UPDATE BETS SET is_settled = %s WHERE bet_id = %s", (1, bet_id))

            stake_update = self.stake_management_service.record_stake_transaction(
                session_id=session_id,
                gambler_id=gambler_id,
                transaction_type=transaction_type,
                amount=settlement_amount,
                bet_id=bet_id,
                game_id=int(game_id),
                increment_games=True,
            )
        except Exception:
            self.connection.rollback()
            raise

        return {
            "settlement_result": {
                "bet_id": bet_id,
                "game_id": int(game_id),
                "session_id": session_id,
                "gambler_id": gambler_id,
                "outcome": resolved_outcome,
                "payout_amount": payout,
                "loss_amount": loss,
                "stake_before": stake_update["balance_before"],
                "stake_after": stake_update["balance_after"],
                "transaction_ref": stake_update["transaction_ref"],
                "resolved_at": now,
            },
            "updated_stake_values": stake_update["real_time_balance"],
        }
