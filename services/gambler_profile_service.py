from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from models.gambler_profile import BettingPreferences, GamblerProfile


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _row_to_dict(row: Any, description: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    columns = [column[0] for column in description]
    return {columns[index]: row[index] for index in range(len(columns))}


class GamblerProfileService:
    def __init__(self, connection: Any):
        self.connection = connection

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_gambler_exists(self, gambler_id: int) -> None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT gambler_id FROM GAMBLERS WHERE gambler_id = %s", (gambler_id,))
        if cursor.fetchone() is None:
            raise LookupError("Gambler profile not found")

    def _upsert_preferences(self, cursor: Any, gambler_id: int, preference_data: Mapping[str, Any], updated_at: str) -> None:
        allowed_fields = {
            "min_bet",
            "max_bet",
            "preferred_game_type",
            "auto_play_enabled",
            "auto_play_max_games",
            "session_loss_limit",
            "session_win_target",
        }
        money_fields = {"min_bet", "max_bet", "session_loss_limit", "session_win_target"}
        payload = {key: value for key, value in preference_data.items() if key in allowed_fields}
        if not payload:
            return

        cursor.execute("SELECT preference_id FROM BETTING_PREFERENCES WHERE gambler_id = %s", (gambler_id,))
        existing = cursor.fetchone()

        if existing is None:
            columns = ["gambler_id"]
            placeholders = ["%s"]
            values: list[Any] = [gambler_id]
            for key, value in payload.items():
                columns.append(key)
                placeholders.append("%s")
                if key in money_fields:
                    values.append(str(_to_decimal(value)))
                elif key == "auto_play_enabled":
                    values.append(1 if _to_bool(value) else 0)
                else:
                    values.append(value)
            columns.append("updated_at")
            placeholders.append("%s")
            values.append(updated_at)
            query = f"INSERT INTO BETTING_PREFERENCES ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            cursor.execute(query, tuple(values))
        else:
            assignments: list[str] = []
            values = []
            for key, value in payload.items():
                assignments.append(f"{key} = %s")
                if key in money_fields:
                    values.append(str(_to_decimal(value)))
                elif key == "auto_play_enabled":
                    values.append(1 if _to_bool(value) else 0)
                else:
                    values.append(value)
            assignments.append("updated_at = %s")
            values.append(updated_at)
            values.append(gambler_id)
            query = f"UPDATE BETTING_PREFERENCES SET {', '.join(assignments)} WHERE gambler_id = %s"
            cursor.execute(query, tuple(values))

    def _insert_stake_transaction(
        self,
        cursor: Any,
        gambler_id: int,
        transaction_type: str,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        session_id: int | None,
        bet_id: int | None,
        game_id: int | None,
        transaction_ref: str,
        created_at: str,
    ) -> None:
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
                str(amount),
                str(balance_before),
                str(balance_after),
                transaction_ref,
                created_at,
            ),
        )

    def create_gambler_profile(
        self,
        profile_data: Mapping[str, Any],
        preference_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        required_fields = (
            "username",
            "full_name",
            "email",
            "initial_stake",
            "win_threshold",
            "loss_threshold",
            "min_required_stake",
        )
        missing = [field for field in required_fields if field not in profile_data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        now = self._utc_now()
        initial_stake = _to_decimal(profile_data.get("initial_stake"))
        current_stake = _to_decimal(profile_data.get("current_stake", initial_stake))
        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO GAMBLERS (
                username,
                full_name,
                email,
                is_active,
                initial_stake,
                current_stake,
                win_threshold,
                loss_threshold,
                min_required_stake,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(profile_data.get("username", "")).strip(),
                str(profile_data.get("full_name", "")).strip(),
                str(profile_data.get("email", "")).strip(),
                1 if _to_bool(profile_data.get("is_active", True)) else 0,
                str(initial_stake),
                str(current_stake),
                str(_to_decimal(profile_data.get("win_threshold"))),
                str(_to_decimal(profile_data.get("loss_threshold"))),
                str(_to_decimal(profile_data.get("min_required_stake"))),
                now,
                now,
            ),
        )

        gambler_id = cursor.lastrowid
        if gambler_id is None:
            cursor.execute("SELECT gambler_id FROM GAMBLERS WHERE username = %s", (str(profile_data.get("username", "")).strip(),))
            row = cursor.fetchone()
            if row is None:
                self.connection.rollback()
                raise RuntimeError("Failed to resolve created gambler_id")
            if isinstance(row, Mapping):
                gambler_id = row.get("gambler_id")
            elif hasattr(row, "keys"):
                gambler_id = row["gambler_id"]
            else:
                gambler_id = row[0]

        if preference_data is not None:
            self._upsert_preferences(cursor, int(gambler_id), preference_data, now)

        self.connection.commit()
        return self.get_profile(gambler_id=int(gambler_id))

    def get_profile(self, gambler_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                g.gambler_id,
                g.username,
                g.full_name,
                g.email,
                g.is_active,
                g.initial_stake,
                g.current_stake,
                g.win_threshold,
                g.loss_threshold,
                g.min_required_stake,
                g.created_at,
                g.updated_at,
                bp.preference_id,
                bp.min_bet,
                bp.max_bet,
                bp.preferred_game_type,
                bp.auto_play_enabled,
                bp.auto_play_max_games,
                bp.session_loss_limit,
                bp.session_win_target,
                bp.updated_at AS preferences_updated_at
            FROM GAMBLERS g
            LEFT JOIN BETTING_PREFERENCES bp ON bp.gambler_id = g.gambler_id
            WHERE g.gambler_id = %s
            LIMIT 1
            """,
            (gambler_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("Gambler profile not found")

        data = _row_to_dict(row, cursor.description)
        profile = GamblerProfile.from_record(data)
        preferences = None
        if data.get("preference_id") is not None:
            preferences = BettingPreferences.from_record(data)

        return {
            "profile": profile,
            "preferences": preferences,
        }

    def update_gambler_profile(
        self,
        gambler_id: int,
        profile_updates: Mapping[str, Any] | None = None,
        preference_updates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_gambler_exists(gambler_id)
        now = self._utc_now()
        cursor = self.connection.cursor()

        if profile_updates:
            allowed_fields = {
                "username",
                "full_name",
                "email",
                "is_active",
                "initial_stake",
                "current_stake",
                "win_threshold",
                "loss_threshold",
                "min_required_stake",
            }
            money_fields = {
                "initial_stake",
                "current_stake",
                "win_threshold",
                "loss_threshold",
                "min_required_stake",
            }
            assignments: list[str] = []
            values: list[Any] = []
            for key, value in profile_updates.items():
                if key not in allowed_fields:
                    continue
                assignments.append(f"{key} = %s")
                if key in money_fields:
                    values.append(str(_to_decimal(value)))
                elif key == "is_active":
                    values.append(1 if _to_bool(value) else 0)
                else:
                    values.append(str(value).strip())

            if assignments:
                assignments.append("updated_at = %s")
                values.append(now)
                values.append(gambler_id)
                query = f"UPDATE GAMBLERS SET {', '.join(assignments)} WHERE gambler_id = %s"
                cursor.execute(query, tuple(values))

        if preference_updates:
            self._upsert_preferences(cursor, gambler_id, preference_updates, now)

        self.connection.commit()
        return self.get_profile(gambler_id=gambler_id)

    def validate_eligibility(self, gambler_id: int, proposed_bet: Any | None = None) -> dict[str, Any]:
        data = self.get_profile(gambler_id)
        profile: GamblerProfile = data["profile"]
        preferences: BettingPreferences | None = data["preferences"]

        checks: dict[str, bool] = {
            "is_active": profile.is_active,
            "meets_min_required_stake": profile.current_stake >= profile.min_required_stake,
            "above_loss_threshold": profile.current_stake > profile.loss_threshold,
            "below_win_threshold": profile.current_stake < profile.win_threshold,
        }
        reasons: list[str] = []

        if not checks["is_active"]:
            reasons.append("account_inactive")
        if not checks["meets_min_required_stake"]:
            reasons.append("below_min_required_stake")
        if not checks["above_loss_threshold"]:
            reasons.append("loss_threshold_reached")
        if not checks["below_win_threshold"]:
            reasons.append("win_threshold_reached")

        proposed_bet_decimal = None
        if proposed_bet is not None:
            proposed_bet_decimal = _to_decimal(proposed_bet)
            checks["bet_positive"] = proposed_bet_decimal > 0
            checks["bet_within_current_stake"] = proposed_bet_decimal <= profile.current_stake
            checks["post_bet_above_min_required_stake"] = (profile.current_stake - proposed_bet_decimal) >= profile.min_required_stake

            if preferences is not None:
                checks["meets_preference_min_bet"] = proposed_bet_decimal >= preferences.min_bet if preferences.min_bet > 0 else True
                checks["within_preference_max_bet"] = proposed_bet_decimal <= preferences.max_bet if preferences.max_bet > 0 else True
            else:
                checks["meets_preference_min_bet"] = True
                checks["within_preference_max_bet"] = True

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
            "gambler_id": gambler_id,
            "eligible": len(reasons) == 0,
            "reasons": reasons,
            "checks": checks,
            "proposed_bet": proposed_bet_decimal,
            "current_stake": profile.current_stake,
            "min_required_stake": profile.min_required_stake,
            "win_threshold": profile.win_threshold,
            "loss_threshold": profile.loss_threshold,
        }

    def reset_gambler_profile(
        self,
        gambler_id: int,
        reset_stake: Any | None = None,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        data = self.get_profile(gambler_id)
        profile: GamblerProfile = data["profile"]

        balance_before = profile.current_stake
        balance_after = profile.initial_stake if reset_stake is None else _to_decimal(reset_stake)
        amount = balance_after - balance_before
        transaction_ref = f"RST-{uuid4().hex}"
        now = self._utc_now()

        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE GAMBLERS SET current_stake = %s, updated_at = %s WHERE gambler_id = %s",
            (str(balance_after), now, gambler_id),
        )
        self._insert_stake_transaction(
            cursor=cursor,
            gambler_id=gambler_id,
            transaction_type="RESET",
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            session_id=session_id,
            bet_id=None,
            game_id=None,
            transaction_ref=transaction_ref,
            created_at=now,
        )
        self.connection.commit()

        return {
            "gambler_id": gambler_id,
            "transaction_ref": transaction_ref,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "current_financial_status": self.get_current_financial_status(gambler_id),
        }

    def adjust_stake(
        self,
        gambler_id: int,
        amount: Any,
        transaction_type: str = "ADJUSTMENT",
        session_id: int | None = None,
        bet_id: int | None = None,
        game_id: int | None = None,
    ) -> dict[str, Any]:
        data = self.get_profile(gambler_id)
        profile: GamblerProfile = data["profile"]

        amount_decimal = _to_decimal(amount)
        balance_before = profile.current_stake
        balance_after = balance_before + amount_decimal
        if balance_after < 0:
            raise ValueError("Adjustment would result in negative current_stake")

        transaction_ref = f"ADJ-{uuid4().hex}"
        now = self._utc_now()
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE GAMBLERS SET current_stake = %s, updated_at = %s WHERE gambler_id = %s",
            (str(balance_after), now, gambler_id),
        )
        self._insert_stake_transaction(
            cursor=cursor,
            gambler_id=gambler_id,
            transaction_type=transaction_type,
            amount=amount_decimal,
            balance_before=balance_before,
            balance_after=balance_after,
            session_id=session_id,
            bet_id=bet_id,
            game_id=game_id,
            transaction_ref=transaction_ref,
            created_at=now,
        )
        self.connection.commit()

        return {
            "gambler_id": gambler_id,
            "transaction_ref": transaction_ref,
            "amount": amount_decimal,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "current_financial_status": self.get_current_financial_status(gambler_id),
        }

    def get_current_financial_status(self, gambler_id: int) -> dict[str, Any]:
        data = self.get_profile(gambler_id)
        profile: GamblerProfile = data["profile"]
        return profile.current_financial_status()

    def get_profile_summary(self, gambler_id: int) -> dict[str, Any]:
        data = self.get_profile(gambler_id)
        profile: GamblerProfile = data["profile"]
        preferences: BettingPreferences | None = data["preferences"]
        return profile.profile_summary(preferences)

    def get_uc01_outputs(self, gambler_id: int, proposed_bet: Any | None = None) -> dict[str, Any]:
        return {
            "current_financial_status": self.get_current_financial_status(gambler_id),
            "profile_summary": self.get_profile_summary(gambler_id),
            "eligibility_status": self.validate_eligibility(gambler_id, proposed_bet),
        }
