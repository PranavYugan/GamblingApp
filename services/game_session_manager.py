from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from models.session_models import DurationMetrics, PauseRecord, SessionParametersRecord, SessionRecord


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


class GameSessionManager:
    def __init__(self, connection: Any):
        self.connection = connection

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _utc_now_str(self) -> str:
        return self._utc_now().isoformat()

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

    def _fetch_session_record(self, session_id: int) -> SessionRecord:
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
                total_pause_seconds,
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
        return SessionRecord.from_record(_row_to_dict(row, cursor.description))

    def _fetch_latest_live_session_for_gambler(self, gambler_id: int) -> SessionRecord | None:
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
                total_pause_seconds,
                started_at,
                ended_at,
                created_at
            FROM SESSIONS
            WHERE gambler_id = %s
              AND status IN ('ACTIVE', 'PAUSED')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (gambler_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SessionRecord.from_record(_row_to_dict(row, cursor.description))

    def _fetch_session_parameters(self, session_id: int) -> SessionParametersRecord | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                parameter_id,
                session_id,
                lower_limit,
                upper_limit,
                min_bet,
                max_bet,
                default_win_probability,
                max_session_minutes,
                strict_mode,
                created_at
            FROM SESSION_PARAMETERS
            WHERE session_id = %s
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SessionParametersRecord.from_record(_row_to_dict(row, cursor.description))

    def _fetch_open_pause_record(self, session_id: int) -> PauseRecord | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                pause_id,
                session_id,
                pause_reason,
                paused_at,
                resumed_at,
                pause_seconds
            FROM PAUSE_RECORDS
            WHERE session_id = %s
              AND resumed_at IS NULL
            ORDER BY paused_at DESC, pause_id DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return PauseRecord.from_record(_row_to_dict(row, cursor.description))

    def _duration_metrics(self, session: SessionRecord, open_pause: PauseRecord | None = None) -> DurationMetrics:
        if session.started_at is None:
            return DurationMetrics(total_seconds=0, paused_seconds=0, active_seconds=0)

        now_dt = self._utc_now()
        end_dt = session.ended_at or now_dt
        total_seconds = int(max((end_dt - session.started_at).total_seconds(), 0))
        paused_seconds = max(session.total_pause_seconds, 0)

        if open_pause is not None and open_pause.paused_at is not None and open_pause.resumed_at is None:
            paused_seconds += int(max((now_dt - open_pause.paused_at).total_seconds(), 0))

        active_seconds = total_seconds - paused_seconds
        if active_seconds < 0:
            active_seconds = 0

        return DurationMetrics(total_seconds=total_seconds, paused_seconds=paused_seconds, active_seconds=active_seconds)

    def _session_game_summary(self, session_id: int) -> dict[str, Any]:
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
                COALESCE(SUM(net_change), 0) AS total_net_change
            FROM GAME_RECORDS
            WHERE session_id = %s
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        data = _row_to_dict(row, cursor.description)
        return {
            "total_games": _to_int(data.get("total_games"), 0),
            "total_wins": _to_int(data.get("total_wins"), 0),
            "total_losses": _to_int(data.get("total_losses"), 0),
            "total_pushes": _to_int(data.get("total_pushes"), 0),
            "total_payout": _to_decimal(data.get("total_payout")),
            "total_loss_amount": _to_decimal(data.get("total_loss_amount")),
            "total_net_change": _to_decimal(data.get("total_net_change")),
        }

    def _session_pause_summary(self, session_id: int) -> dict[str, Any]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) AS pause_count,
                COALESCE(SUM(pause_seconds), 0) AS logged_pause_seconds
            FROM PAUSE_RECORDS
            WHERE session_id = %s
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        data = _row_to_dict(row, cursor.description)
        return {
            "pause_count": _to_int(data.get("pause_count"), 0),
            "logged_pause_seconds": _to_int(data.get("logged_pause_seconds"), 0),
        }

    def _compose_state(self, session: SessionRecord, parameters: SessionParametersRecord | None) -> dict[str, Any]:
        open_pause = self._fetch_open_pause_record(session.session_id or 0)
        duration_metrics = self._duration_metrics(session, open_pause)
        game_summary = self._session_game_summary(session.session_id or 0)
        pause_summary = self._session_pause_summary(session.session_id or 0)

        ending_stake = session.ending_stake
        if session.status in {"ACTIVE", "PAUSED"}:
            gambler = self._fetch_gambler(session.gambler_id or 0)
            ending_stake = _to_decimal(gambler.get("current_stake"))

        summary = {
            "starting_stake": session.starting_stake,
            "ending_stake": ending_stake,
            "net_change": ending_stake - session.starting_stake,
            "peak_stake": session.peak_stake,
            "lowest_stake": session.lowest_stake,
            "stake_spread": session.peak_stake - session.lowest_stake,
            "games": game_summary,
            "pauses": pause_summary,
        }

        return {
            "session_lifecycle_state": {
                "session_id": session.session_id,
                "gambler_id": session.gambler_id,
                "status": session.status,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "games_played": session.games_played,
                "max_games": session.max_games,
                "is_paused": session.status == "PAUSED",
            },
            "duration_metrics": duration_metrics.to_dict(),
            "end_reason": session.end_reason,
            "summary": summary,
            "parameters": parameters.to_dict() if parameters else None,
        }

    def start_session(
        self,
        gambler_id: int,
        max_games: int | None = None,
        lower_limit: Any | None = None,
        upper_limit: Any | None = None,
        min_bet: Any | None = None,
        max_bet: Any | None = None,
        default_win_probability: Any | None = None,
        max_session_minutes: int | None = None,
        strict_mode: bool = True,
    ) -> dict[str, Any]:
        gambler = self._fetch_gambler(gambler_id)
        if int(gambler.get("is_active") or 0) != 1:
            raise ValueError("Gambler account is inactive")

        existing = self._fetch_latest_live_session_for_gambler(gambler_id)
        if existing is not None:
            return self.get_session_lifecycle_state(existing.session_id or 0)

        current_stake = _to_decimal(gambler.get("current_stake"))
        resolved_max_games = 100 if max_games is None else int(max_games)
        if resolved_max_games <= 0:
            raise ValueError("max_games must be a positive integer")

        loss_threshold = _to_decimal(gambler.get("loss_threshold"))
        win_threshold = _to_decimal(gambler.get("win_threshold"))

        resolved_lower_limit = _to_decimal(lower_limit) if lower_limit is not None else loss_threshold
        resolved_upper_limit = _to_decimal(upper_limit) if upper_limit is not None else win_threshold
        resolved_min_bet = _to_decimal(min_bet) if min_bet is not None else Decimal("0")
        resolved_max_bet = _to_decimal(max_bet) if max_bet is not None else Decimal("0")
        resolved_win_probability = (
            _to_decimal(default_win_probability) if default_win_probability is not None else Decimal("0.500000")
        )
        resolved_max_minutes = 120 if max_session_minutes is None else int(max_session_minutes)

        if resolved_win_probability < 0 or resolved_win_probability > 1:
            raise ValueError("default_win_probability must be between 0 and 1")
        if resolved_max_minutes <= 0:
            raise ValueError("max_session_minutes must be a positive integer")

        now = self._utc_now_str()
        cursor = self.connection.cursor()
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
                str(current_stake),
                str(current_stake),
                str(current_stake),
                str(current_stake),
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

        cursor.execute(
            """
            INSERT INTO SESSION_PARAMETERS (
                session_id,
                lower_limit,
                upper_limit,
                min_bet,
                max_bet,
                default_win_probability,
                max_session_minutes,
                strict_mode,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(session_id),
                str(resolved_lower_limit),
                str(resolved_upper_limit),
                str(resolved_min_bet),
                str(resolved_max_bet),
                str(resolved_win_probability),
                resolved_max_minutes,
                1 if strict_mode else 0,
                now,
            ),
        )
        self.connection.commit()

        auto_state = self.auto_end_if_needed(int(session_id))
        return {
            "auto_ended": auto_state["auto_ended"],
            "trigger_reason": auto_state["trigger_reason"],
            **auto_state["state"],
        }

    def continue_session(self, session_id: int) -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        if session.status == "PAUSED":
            return self.resume_session(session_id)
        auto_state = self.auto_end_if_needed(session_id)
        return {
            "auto_ended": auto_state["auto_ended"],
            "trigger_reason": auto_state["trigger_reason"],
            **auto_state["state"],
        }

    def pause_session(self, session_id: int, pause_reason: str | None = None) -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        if session.status != "ACTIVE":
            raise ValueError("Only ACTIVE sessions can be paused")

        now = self._utc_now_str()
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO PAUSE_RECORDS (
                session_id,
                pause_reason,
                paused_at,
                resumed_at,
                pause_seconds
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                session_id,
                pause_reason,
                now,
                None,
                None,
            ),
        )
        cursor.execute("UPDATE SESSIONS SET status = %s WHERE session_id = %s", ("PAUSED", session_id))
        self.connection.commit()
        return self.get_session_lifecycle_state(session_id)

    def resume_session(self, session_id: int) -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        if session.status == "ACTIVE":
            auto_state = self.auto_end_if_needed(session_id)
            return {
                "auto_ended": auto_state["auto_ended"],
                "trigger_reason": auto_state["trigger_reason"],
                **auto_state["state"],
            }
        if session.status != "PAUSED":
            raise ValueError("Only PAUSED sessions can be resumed")

        open_pause = self._fetch_open_pause_record(session_id)
        now_dt = self._utc_now()
        now = now_dt.isoformat()

        cursor = self.connection.cursor()
        added_pause_seconds = 0
        if open_pause is not None and open_pause.paused_at is not None:
            added_pause_seconds = int(max((now_dt - open_pause.paused_at).total_seconds(), 0))
            cursor.execute(
                "UPDATE PAUSE_RECORDS SET resumed_at = %s, pause_seconds = %s WHERE pause_id = %s",
                (now, added_pause_seconds, open_pause.pause_id),
            )

        cursor.execute(
            """
            UPDATE SESSIONS
            SET
                status = %s,
                total_pause_seconds = total_pause_seconds + %s
            WHERE session_id = %s
            """,
            (
                "ACTIVE",
                added_pause_seconds,
                session_id,
            ),
        )
        self.connection.commit()

        auto_state = self.auto_end_if_needed(session_id)
        return {
            "auto_ended": auto_state["auto_ended"],
            "trigger_reason": auto_state["trigger_reason"],
            **auto_state["state"],
        }

    def end_session(self, session_id: int, end_reason: str = "MANUAL_END") -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        if session.status == "COMPLETED":
            return self.get_session_lifecycle_state(session_id)

        now_dt = self._utc_now()
        now = now_dt.isoformat()
        cursor = self.connection.cursor()

        additional_pause_seconds = 0
        if session.status == "PAUSED":
            open_pause = self._fetch_open_pause_record(session_id)
            if open_pause is not None and open_pause.paused_at is not None:
                additional_pause_seconds = int(max((now_dt - open_pause.paused_at).total_seconds(), 0))
                cursor.execute(
                    "UPDATE PAUSE_RECORDS SET resumed_at = %s, pause_seconds = %s WHERE pause_id = %s",
                    (now, additional_pause_seconds, open_pause.pause_id),
                )

        gambler = self._fetch_gambler(session.gambler_id or 0)
        current_stake = _to_decimal(gambler.get("current_stake"))
        peak_stake = max(session.peak_stake, current_stake)
        lowest_stake = min(session.lowest_stake, current_stake)

        cursor.execute(
            """
            UPDATE SESSIONS
            SET
                status = %s,
                end_reason = %s,
                ending_stake = %s,
                peak_stake = %s,
                lowest_stake = %s,
                total_pause_seconds = total_pause_seconds + %s,
                ended_at = %s
            WHERE session_id = %s
            """,
            (
                "COMPLETED",
                end_reason,
                str(current_stake),
                str(peak_stake),
                str(lowest_stake),
                additional_pause_seconds,
                now,
                session_id,
            ),
        )
        self.connection.commit()
        return self.get_session_lifecycle_state(session_id)

    def auto_end_if_needed(self, session_id: int) -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        if session.status != "ACTIVE":
            return {
                "auto_ended": False,
                "trigger_reason": None,
                "state": self.get_session_lifecycle_state(session_id),
            }

        gambler = self._fetch_gambler(session.gambler_id or 0)
        params = self._fetch_session_parameters(session_id)
        current_stake = _to_decimal(gambler.get("current_stake"))
        duration = self._duration_metrics(session)

        max_games_trigger = session.max_games > 0 and session.games_played >= session.max_games
        max_duration_trigger = (
            params is not None
            and params.max_session_minutes > 0
            and duration.active_seconds >= params.max_session_minutes * 60
        )

        trigger_reason: str | None = None
        if max_games_trigger:
            trigger_reason = "MAX_GAMES_REACHED"
        elif max_duration_trigger:
            trigger_reason = "MAX_DURATION_REACHED"

        strict_mode = True if params is None else params.strict_mode
        if trigger_reason is None and strict_mode:
            lower_limit = params.lower_limit if params is not None else Decimal("0")
            upper_limit = params.upper_limit if params is not None else Decimal("0")
            loss_threshold = _to_decimal(gambler.get("loss_threshold"))
            win_threshold = _to_decimal(gambler.get("win_threshold"))

            if lower_limit > 0 and current_stake <= lower_limit:
                trigger_reason = "LOWER_LIMIT_REACHED"
            elif upper_limit > 0 and current_stake >= upper_limit:
                trigger_reason = "UPPER_LIMIT_REACHED"
            elif loss_threshold > 0 and current_stake <= loss_threshold:
                trigger_reason = "LOSS_THRESHOLD_REACHED"
            elif win_threshold > 0 and current_stake >= win_threshold:
                trigger_reason = "WIN_THRESHOLD_REACHED"

        if trigger_reason is not None:
            state = self.end_session(session_id=session_id, end_reason=trigger_reason)
            return {
                "auto_ended": True,
                "trigger_reason": trigger_reason,
                "state": state,
            }

        return {
            "auto_ended": False,
            "trigger_reason": None,
            "state": self.get_session_lifecycle_state(session_id),
        }

    def get_session_lifecycle_state(self, session_id: int) -> dict[str, Any]:
        session = self._fetch_session_record(session_id)
        parameters = self._fetch_session_parameters(session_id)
        return self._compose_state(session, parameters)
