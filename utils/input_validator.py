from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from utils.exceptions import RecoverableValidationException, ValidationException, ValidationIssue


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc


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


def _classification(issues: list[ValidationIssue]) -> str:
    if any(issue.severity == "ERROR" for issue in issues):
        return "ERROR"
    if any(issue.severity == "WARNING" for issue in issues):
        return "WARNING"
    return "OK"


class InputValidator:
    def __init__(self, connection: Any):
        self.connection = connection

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_issue(
        self,
        issues: list[ValidationIssue],
        code: str,
        message: str,
        field_name: str | None,
        severity: str,
        recoverable: bool,
        user_feedback: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                message=message,
                field_name=field_name,
                severity=severity,
                recoverable=recoverable,
                user_feedback=user_feedback,
                context=dict(context or {}),
            )
        )

    def _build_result(
        self,
        scope: str,
        issues: list[ValidationIssue],
        checks: Mapping[str, Any],
        context: Mapping[str, Any] | None,
        event_ids: list[int],
    ) -> dict[str, Any]:
        warnings = [issue.to_dict() for issue in issues if issue.severity == "WARNING"]
        errors = [issue.to_dict() for issue in issues if issue.severity == "ERROR"]
        recoverable_feedback_messages = [
            {
                "severity": issue.severity,
                "code": issue.code,
                "field_name": issue.field_name,
                "recoverable": issue.recoverable,
                "message": issue.message,
                "user_feedback": issue.user_feedback,
            }
            for issue in issues
            if issue.recoverable
        ]
        return {
            "scope": scope,
            "valid": len(errors) == 0,
            "classification": _classification(issues),
            "checks": dict(checks),
            "warnings": warnings,
            "errors": errors,
            "issues": [issue.to_dict() for issue in issues],
            "recoverable_feedback_messages": recoverable_feedback_messages,
            "event_ids": event_ids,
            "context": dict(context or {}),
        }

    def _raise_if_requested(self, result: Mapping[str, Any], raise_on_error: bool) -> None:
        if not raise_on_error:
            return
        if bool(result.get("valid", False)):
            return
        errors = result.get("errors") or []
        message = "; ".join(str(error.get("message", "Validation failed")) for error in errors)
        if all(bool(error.get("recoverable", True)) for error in errors):
            raise RecoverableValidationException(message=message, details={"result": dict(result)})
        raise ValidationException(message=message, recoverable=False, details={"result": dict(result)})

    def _record_exists(self, table_name: str, id_column: str, value: int | None) -> bool:
        if value is None:
            return False
        cursor = self.connection.cursor()
        cursor.execute(f"SELECT 1 FROM {table_name} WHERE {id_column} = %s LIMIT 1", (value,))
        return cursor.fetchone() is not None

    def _persist_validation_events(
        self,
        scope: str,
        issues: list[ValidationIssue],
        gambler_id: int | None,
        session_id: int | None,
        bet_id: int | None,
        inputs: Mapping[str, Any] | None,
    ) -> list[int]:
        if not issues:
            return []
        resolved_inputs = dict(inputs or {})
        resolved_gambler_id = gambler_id if self._record_exists("GAMBLERS", "gambler_id", gambler_id) else None
        resolved_session_id = session_id if self._record_exists("SESSIONS", "session_id", session_id) else None
        resolved_bet_id = bet_id if self._record_exists("BETS", "bet_id", bet_id) else None
        cursor = self.connection.cursor()
        event_ids: list[int] = []

        for issue in issues:
            field_name = issue.field_name
            if field_name is not None and field_name in resolved_inputs:
                input_value = resolved_inputs.get(field_name)
            elif len(resolved_inputs) == 1:
                input_value = next(iter(resolved_inputs.values()))
            else:
                input_value = None
            cursor.execute(
                """
                INSERT INTO VALIDATION_EVENTS (
                    gambler_id,
                    session_id,
                    bet_id,
                    validation_scope,
                    field_name,
                    input_value,
                    severity,
                    error_code,
                    message,
                    recoverable,
                    user_feedback,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    resolved_gambler_id,
                    resolved_session_id,
                    resolved_bet_id,
                    scope,
                    field_name,
                    None if input_value is None else str(input_value),
                    issue.severity,
                    issue.code,
                    issue.message,
                    1 if issue.recoverable else 0,
                    issue.user_feedback,
                    self._utc_now(),
                ),
            )
            if cursor.lastrowid is not None:
                event_ids.append(int(cursor.lastrowid))

        self.connection.commit()
        return event_ids

    def _fetch_gambler_snapshot(self, gambler_id: int) -> dict[str, Any] | None:
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
        return None if row is None else _row_to_dict(row, cursor.description)

    def _fetch_session_snapshot(self, session_id: int) -> dict[str, Any] | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                session_id,
                gambler_id,
                status,
                max_games,
                games_played,
                starting_stake,
                ending_stake,
                peak_stake,
                lowest_stake
            FROM SESSIONS
            WHERE session_id = %s
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        return None if row is None else _row_to_dict(row, cursor.description)

    def _fetch_session_parameters_snapshot(self, session_id: int) -> dict[str, Any] | None:
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
                strict_mode
            FROM SESSION_PARAMETERS
            WHERE session_id = %s
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        return None if row is None else _row_to_dict(row, cursor.description)

    def _fetch_bet_snapshot(self, bet_id: int) -> dict[str, Any] | None:
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
                is_settled,
                placed_at
            FROM BETS
            WHERE bet_id = %s
            LIMIT 1
            """,
            (bet_id,),
        )
        row = cursor.fetchone()
        return None if row is None else _row_to_dict(row, cursor.description)

    def _count_unsettled_bets(self, session_id: int) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS unsettled_count FROM BETS WHERE session_id = %s AND is_settled = %s",
            (session_id, 0),
        )
        row = cursor.fetchone()
        data = _row_to_dict(row, cursor.description)
        return int(data.get("unsettled_count") or 0)

    def _validate_numeric_value(
        self,
        field_name: str,
        value: Any,
        min_value: Any | None,
        max_value: Any | None,
        allow_zero: bool,
        allow_none: bool,
    ) -> tuple[Decimal | None, dict[str, Any], list[ValidationIssue]]:
        issues: list[ValidationIssue] = []
        checks: dict[str, Any] = {
            "provided": value is not None and value != "",
            "numeric": False,
            "non_negative": False,
            "within_min": True,
            "within_max": True,
            "non_zero": True,
        }

        if value is None or value == "":
            if allow_none:
                checks["non_negative"] = True
                return None, checks, issues
            self._append_issue(
                issues=issues,
                code="REQUIRED_FIELD_MISSING",
                message=f"{field_name} is required",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"Provide a valid value for {field_name}.",
            )
            return None, checks, issues

        try:
            parsed_value = _to_decimal(value)
            checks["numeric"] = True
        except ValueError:
            self._append_issue(
                issues=issues,
                code="INVALID_NUMERIC_VALUE",
                message=f"{field_name} must be numeric",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"Use a numeric value for {field_name}.",
            )
            return None, checks, issues

        if parsed_value < 0:
            checks["non_negative"] = False
            self._append_issue(
                issues=issues,
                code="NEGATIVE_VALUE_NOT_ALLOWED",
                message=f"{field_name} must be non-negative",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"{field_name} cannot be negative.",
            )
        else:
            checks["non_negative"] = True

        if not allow_zero and parsed_value == 0:
            checks["non_zero"] = False
            self._append_issue(
                issues=issues,
                code="ZERO_VALUE_NOT_ALLOWED",
                message=f"{field_name} must be greater than zero",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"Increase {field_name} to a value greater than zero.",
            )

        min_decimal = None if min_value is None else _to_decimal(min_value)
        max_decimal = None if max_value is None else _to_decimal(max_value)

        if min_decimal is not None and max_decimal is not None and min_decimal > max_decimal:
            self._append_issue(
                issues=issues,
                code="INVALID_VALIDATION_RANGE",
                message="min_value cannot be greater than max_value",
                field_name=field_name,
                severity="ERROR",
                recoverable=False,
                user_feedback="Validation range configuration is invalid.",
            )

        if min_decimal is not None and parsed_value < min_decimal:
            checks["within_min"] = False
            self._append_issue(
                issues=issues,
                code="VALUE_BELOW_MINIMUM",
                message=f"{field_name} must be at least {min_decimal}",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"Increase {field_name} to at least {min_decimal}.",
            )

        if max_decimal is not None and parsed_value > max_decimal:
            checks["within_max"] = False
            self._append_issue(
                issues=issues,
                code="VALUE_ABOVE_MAXIMUM",
                message=f"{field_name} must be at most {max_decimal}",
                field_name=field_name,
                severity="ERROR",
                recoverable=True,
                user_feedback=f"Reduce {field_name} to at most {max_decimal}.",
            )

        if min_decimal is not None and min_decimal > 0 and parsed_value >= min_decimal and parsed_value <= (min_decimal * Decimal("1.05")):
            self._append_issue(
                issues=issues,
                code="VALUE_NEAR_MINIMUM",
                message=f"{field_name} is close to minimum threshold",
                field_name=field_name,
                severity="WARNING",
                recoverable=True,
                user_feedback=f"{field_name} is near the minimum threshold.",
            )

        if max_decimal is not None and max_decimal > 0 and parsed_value <= max_decimal and parsed_value >= (max_decimal * Decimal("0.95")):
            self._append_issue(
                issues=issues,
                code="VALUE_NEAR_MAXIMUM",
                message=f"{field_name} is close to maximum threshold",
                field_name=field_name,
                severity="WARNING",
                recoverable=True,
                user_feedback=f"{field_name} is near the maximum threshold.",
            )

        return parsed_value, checks, issues

    def _validate_probability_value(self, field_name: str, probability: Any) -> tuple[Decimal | None, dict[str, Any], list[ValidationIssue]]:
        parsed_probability, checks, issues = self._validate_numeric_value(
            field_name=field_name,
            value=probability,
            min_value=Decimal("0"),
            max_value=Decimal("1"),
            allow_zero=True,
            allow_none=False,
        )
        if parsed_probability is None:
            return None, checks, issues

        checks["between_zero_and_one"] = Decimal("0") <= parsed_probability <= Decimal("1")
        if parsed_probability == Decimal("0"):
            self._append_issue(
                issues=issues,
                code="ZERO_PROBABILITY",
                message=f"{field_name} is zero and guarantees loss",
                field_name=field_name,
                severity="WARNING",
                recoverable=True,
                user_feedback=f"Increase {field_name} above 0 to allow potential wins.",
            )
        if parsed_probability == Decimal("1"):
            self._append_issue(
                issues=issues,
                code="UNIT_PROBABILITY",
                message=f"{field_name} is one and guarantees win",
                field_name=field_name,
                severity="WARNING",
                recoverable=True,
                user_feedback=f"Lower {field_name} below 1 for realistic odds.",
            )
        return parsed_probability, checks, issues

    def validate_numeric_input(
        self,
        field_name: str,
        value: Any,
        min_value: Any | None = None,
        max_value: Any | None = None,
        allow_zero: bool = True,
        allow_none: bool = False,
        gambler_id: int | None = None,
        session_id: int | None = None,
        bet_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        parsed_value, checks, issues = self._validate_numeric_value(
            field_name=field_name,
            value=value,
            min_value=min_value,
            max_value=max_value,
            allow_zero=allow_zero,
            allow_none=allow_none,
        )
        event_ids = self._persist_validation_events(
            scope="NUMERIC_INPUT",
            issues=issues,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=bet_id,
            inputs={field_name: value},
        )
        result = self._build_result(
            scope="NUMERIC_INPUT",
            issues=issues,
            checks=checks,
            context={
                "field_name": field_name,
                "input_value": value,
                "parsed_value": parsed_value,
                "min_value": min_value,
                "max_value": max_value,
            },
            event_ids=event_ids,
        )
        self._raise_if_requested(result, raise_on_error)
        return result

    def validate_probability(
        self,
        probability: Any,
        field_name: str = "win_probability",
        gambler_id: int | None = None,
        session_id: int | None = None,
        bet_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        parsed_probability, checks, issues = self._validate_probability_value(field_name=field_name, probability=probability)
        event_ids = self._persist_validation_events(
            scope="PROBABILITY",
            issues=issues,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=bet_id,
            inputs={field_name: probability},
        )
        result = self._build_result(
            scope="PROBABILITY",
            issues=issues,
            checks=checks,
            context={
                "field_name": field_name,
                "input_probability": probability,
                "parsed_probability": parsed_probability,
            },
            event_ids=event_ids,
        )
        self._raise_if_requested(result, raise_on_error)
        return result

    def validate_non_negative_balance(
        self,
        balance: Any,
        gambler_id: int | None = None,
        session_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        parsed_balance, checks, issues = self._validate_numeric_value(
            field_name="balance",
            value=balance,
            min_value=Decimal("0"),
            max_value=None,
            allow_zero=True,
            allow_none=False,
        )

        gambler_snapshot = None
        if gambler_id is not None:
            gambler_snapshot = self._fetch_gambler_snapshot(gambler_id)
            checks["gambler_exists"] = gambler_snapshot is not None
            if gambler_snapshot is None:
                self._append_issue(
                    issues=issues,
                    code="GAMBLER_NOT_FOUND",
                    message="Gambler profile not found",
                    field_name="gambler_id",
                    severity="ERROR",
                    recoverable=True,
                    user_feedback="Select a valid gambler profile.",
                )
            else:
                profile_balance = _to_decimal(gambler_snapshot.get("current_stake"))
                min_required_stake = _to_decimal(gambler_snapshot.get("min_required_stake"))
                checks["profile_balance_non_negative"] = profile_balance >= 0
                checks["gambler_active"] = int(gambler_snapshot.get("is_active") or 0) == 1
                if profile_balance < 0:
                    self._append_issue(
                        issues=issues,
                        code="NEGATIVE_PROFILE_BALANCE",
                        message="Stored gambler balance is negative",
                        field_name="current_stake",
                        severity="ERROR",
                        recoverable=False,
                        user_feedback="Account balance data must be corrected before continuing.",
                    )
                if parsed_balance is not None and parsed_balance < min_required_stake:
                    self._append_issue(
                        issues=issues,
                        code="BALANCE_BELOW_MIN_REQUIRED_STAKE",
                        message="Balance falls below gambler minimum required stake",
                        field_name="balance",
                        severity="ERROR",
                        recoverable=True,
                        user_feedback="Increase balance or lower the minimum required stake.",
                    )
                if parsed_balance is not None and profile_balance != parsed_balance:
                    self._append_issue(
                        issues=issues,
                        code="BALANCE_MISMATCH",
                        message="Input balance differs from stored profile balance",
                        field_name="balance",
                        severity="WARNING",
                        recoverable=True,
                        user_feedback="Use the latest balance before placing bets.",
                    )

        event_ids = self._persist_validation_events(
            scope="BALANCE",
            issues=issues,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=None,
            inputs={"balance": balance},
        )
        result = self._build_result(
            scope="BALANCE",
            issues=issues,
            checks=checks,
            context={
                "input_balance": balance,
                "parsed_balance": parsed_balance,
                "gambler_snapshot": gambler_snapshot,
            },
            event_ids=event_ids,
        )
        self._raise_if_requested(result, raise_on_error)
        return result

    def validate_bet_reference(
        self,
        bet_id: int,
        gambler_id: int | None = None,
        session_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        issues: list[ValidationIssue] = []
        bet_snapshot = self._fetch_bet_snapshot(bet_id)
        checks["bet_exists"] = bet_snapshot is not None

        if bet_snapshot is None:
            self._append_issue(
                issues=issues,
                code="BET_NOT_FOUND",
                message="Bet reference not found",
                field_name="bet_id",
                severity="ERROR",
                recoverable=True,
                user_feedback="Use an existing bet id.",
            )
            event_ids = self._persist_validation_events(
                scope="BET_REFERENCE",
                issues=issues,
                gambler_id=gambler_id,
                session_id=session_id,
                bet_id=bet_id,
                inputs={"bet_id": bet_id},
            )
            result = self._build_result(
                scope="BET_REFERENCE",
                issues=issues,
                checks=checks,
                context={"bet_id": bet_id},
                event_ids=event_ids,
            )
            self._raise_if_requested(result, raise_on_error)
            return result

        bet_gambler_id = int(bet_snapshot.get("gambler_id") or 0)
        bet_session_id = int(bet_snapshot.get("session_id") or 0)
        bet_amount = _to_decimal(bet_snapshot.get("bet_amount"))

        checks["bet_amount_positive"] = bet_amount > 0
        checks["matches_gambler"] = True if gambler_id is None else bet_gambler_id == gambler_id
        checks["matches_session"] = True if session_id is None else bet_session_id == session_id
        checks["is_settled"] = int(bet_snapshot.get("is_settled") or 0) == 1

        if not checks["bet_amount_positive"]:
            self._append_issue(
                issues=issues,
                code="INVALID_BET_AMOUNT",
                message="Stored bet amount must be greater than zero",
                field_name="bet_amount",
                severity="ERROR",
                recoverable=False,
                user_feedback="Bet data must be corrected before settlement.",
            )
        if not checks["matches_gambler"]:
            self._append_issue(
                issues=issues,
                code="BET_GAMBLER_MISMATCH",
                message="Bet does not belong to provided gambler",
                field_name="gambler_id",
                severity="ERROR",
                recoverable=True,
                user_feedback="Select the correct gambler for this bet.",
            )
        if not checks["matches_session"]:
            self._append_issue(
                issues=issues,
                code="BET_SESSION_MISMATCH",
                message="Bet does not belong to provided session",
                field_name="session_id",
                severity="ERROR",
                recoverable=True,
                user_feedback="Select the correct session for this bet.",
            )
        if checks["is_settled"]:
            self._append_issue(
                issues=issues,
                code="BET_ALREADY_SETTLED",
                message="Bet is already settled",
                field_name="bet_id",
                severity="WARNING",
                recoverable=True,
                user_feedback="This bet is already finalized.",
            )

        probability_value, probability_checks, probability_issues = self._validate_probability_value(
            field_name="win_probability",
            probability=bet_snapshot.get("win_probability"),
        )
        checks.update({f"bet_{key}": value for key, value in probability_checks.items()})
        issues.extend(probability_issues)

        event_ids = self._persist_validation_events(
            scope="BET_REFERENCE",
            issues=issues,
            gambler_id=gambler_id if gambler_id is not None else bet_gambler_id,
            session_id=session_id if session_id is not None else bet_session_id,
            bet_id=bet_id,
            inputs={
                "bet_id": bet_id,
                "bet_amount": bet_snapshot.get("bet_amount"),
                "win_probability": bet_snapshot.get("win_probability"),
            },
        )
        result = self._build_result(
            scope="BET_REFERENCE",
            issues=issues,
            checks=checks,
            context={
                "bet_snapshot": bet_snapshot,
                "parsed_win_probability": probability_value,
            },
            event_ids=event_ids,
        )
        self._raise_if_requested(result, raise_on_error)
        return result

    def validate_stake_bet_limits(
        self,
        gambler_id: int,
        session_id: int,
        bet_amount: Any,
        win_probability: Any | None = None,
        bet_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        issues: list[ValidationIssue] = []

        parsed_bet_amount, amount_checks, amount_issues = self._validate_numeric_value(
            field_name="bet_amount",
            value=bet_amount,
            min_value=Decimal("0"),
            max_value=None,
            allow_zero=False,
            allow_none=False,
        )
        checks.update({f"bet_amount_{key}": value for key, value in amount_checks.items()})
        issues.extend(amount_issues)

        parsed_probability = None
        if win_probability is not None:
            parsed_probability, probability_checks, probability_issues = self._validate_probability_value(
                field_name="win_probability",
                probability=win_probability,
            )
            checks.update({f"win_probability_{key}": value for key, value in probability_checks.items()})
            issues.extend(probability_issues)

        gambler_snapshot = self._fetch_gambler_snapshot(gambler_id)
        checks["gambler_exists"] = gambler_snapshot is not None
        if gambler_snapshot is None:
            self._append_issue(
                issues=issues,
                code="GAMBLER_NOT_FOUND",
                message="Gambler profile not found",
                field_name="gambler_id",
                severity="ERROR",
                recoverable=True,
                user_feedback="Select a valid gambler before placing a bet.",
            )

        session_snapshot = self._fetch_session_snapshot(session_id)
        checks["session_exists"] = session_snapshot is not None
        if session_snapshot is None:
            self._append_issue(
                issues=issues,
                code="SESSION_NOT_FOUND",
                message="Session not found",
                field_name="session_id",
                severity="ERROR",
                recoverable=True,
                user_feedback="Start or select an active session.",
            )

        session_parameters_snapshot = self._fetch_session_parameters_snapshot(session_id)
        checks["session_parameters_exists"] = session_parameters_snapshot is not None
        if session_parameters_snapshot is None:
            self._append_issue(
                issues=issues,
                code="SESSION_PARAMETERS_MISSING",
                message="Session parameters are missing",
                field_name="session_id",
                severity="WARNING",
                recoverable=True,
                user_feedback="Define session betting limits for stronger validation.",
            )

        if gambler_snapshot is not None and session_snapshot is not None:
            session_gambler_id = int(session_snapshot.get("gambler_id") or 0)
            checks["session_gambler_match"] = session_gambler_id == gambler_id
            if session_gambler_id != gambler_id:
                self._append_issue(
                    issues=issues,
                    code="SESSION_GAMBLER_MISMATCH",
                    message="Session does not belong to gambler",
                    field_name="session_id",
                    severity="ERROR",
                    recoverable=True,
                    user_feedback="Use the session that belongs to this gambler.",
                )

            status = str(session_snapshot.get("status") or "").upper()
            checks["session_active"] = status == "ACTIVE"
            if status == "PAUSED":
                self._append_issue(
                    issues=issues,
                    code="SESSION_PAUSED",
                    message="Session is paused",
                    field_name="session_id",
                    severity="WARNING",
                    recoverable=True,
                    user_feedback="Resume the session before placing bets.",
                )
            elif status != "ACTIVE":
                self._append_issue(
                    issues=issues,
                    code="SESSION_NOT_ACTIVE",
                    message="Session is not active",
                    field_name="session_id",
                    severity="ERROR",
                    recoverable=True,
                    user_feedback="Use an active session for betting.",
                )

            max_games = int(session_snapshot.get("max_games") or 0)
            games_played = int(session_snapshot.get("games_played") or 0)
            checks["max_games_not_reached"] = True if max_games <= 0 else games_played < max_games
            if not checks["max_games_not_reached"]:
                self._append_issue(
                    issues=issues,
                    code="MAX_GAMES_REACHED",
                    message="Session reached max games",
                    field_name="session_id",
                    severity="ERROR",
                    recoverable=True,
                    user_feedback="Start a new session to continue betting.",
                )

            current_stake = _to_decimal(gambler_snapshot.get("current_stake"))
            min_required_stake = _to_decimal(gambler_snapshot.get("min_required_stake"))
            checks["current_stake_non_negative"] = current_stake >= 0
            if current_stake < 0:
                self._append_issue(
                    issues=issues,
                    code="NEGATIVE_CURRENT_STAKE",
                    message="Current stake is negative",
                    field_name="current_stake",
                    severity="ERROR",
                    recoverable=False,
                    user_feedback="Balance data must be fixed before betting.",
                )

            if parsed_bet_amount is not None:
                checks["bet_within_current_stake"] = parsed_bet_amount <= current_stake
                checks["post_bet_non_negative"] = (current_stake - parsed_bet_amount) >= 0
                checks["post_bet_above_min_required_stake"] = (current_stake - parsed_bet_amount) >= min_required_stake

                if parsed_bet_amount > current_stake:
                    self._append_issue(
                        issues=issues,
                        code="BET_EXCEEDS_CURRENT_STAKE",
                        message="Bet amount exceeds current stake",
                        field_name="bet_amount",
                        severity="ERROR",
                        recoverable=True,
                        user_feedback="Lower the bet amount or add funds.",
                    )
                if (current_stake - parsed_bet_amount) < min_required_stake:
                    self._append_issue(
                        issues=issues,
                        code="BET_BREAKS_MIN_REQUIRED_STAKE",
                        message="Bet would drop below minimum required stake",
                        field_name="bet_amount",
                        severity="ERROR",
                        recoverable=True,
                        user_feedback="Reduce the bet to stay above minimum required stake.",
                    )

                if session_parameters_snapshot is not None:
                    min_bet = _to_decimal(session_parameters_snapshot.get("min_bet"))
                    max_bet = _to_decimal(session_parameters_snapshot.get("max_bet"))
                    lower_limit = _to_decimal(session_parameters_snapshot.get("lower_limit"))
                    upper_limit = _to_decimal(session_parameters_snapshot.get("upper_limit"))
                    strict_mode = _to_bool(session_parameters_snapshot.get("strict_mode"))

                    checks["meets_session_min_bet"] = True if min_bet <= 0 else parsed_bet_amount >= min_bet
                    checks["within_session_max_bet"] = True if max_bet <= 0 else parsed_bet_amount <= max_bet

                    if min_bet > 0 and parsed_bet_amount < min_bet:
                        self._append_issue(
                            issues=issues,
                            code="BET_BELOW_SESSION_MIN",
                            message="Bet amount is below session minimum",
                            field_name="bet_amount",
                            severity="ERROR",
                            recoverable=True,
                            user_feedback=f"Increase bet amount to at least {min_bet}.",
                        )
                    if max_bet > 0 and parsed_bet_amount > max_bet:
                        self._append_issue(
                            issues=issues,
                            code="BET_ABOVE_SESSION_MAX",
                            message="Bet amount exceeds session maximum",
                            field_name="bet_amount",
                            severity="ERROR",
                            recoverable=True,
                            user_feedback=f"Reduce bet amount to at most {max_bet}.",
                        )

                    post_bet_balance = current_stake - parsed_bet_amount
                    checks["post_bet_above_lower_limit"] = True if lower_limit <= 0 else post_bet_balance >= lower_limit
                    checks["post_bet_below_upper_limit"] = True if upper_limit <= 0 else post_bet_balance < upper_limit

                    if lower_limit > 0 and post_bet_balance < lower_limit:
                        self._append_issue(
                            issues=issues,
                            code="POST_BET_BELOW_LOWER_LIMIT",
                            message="Post-bet balance falls below lower limit",
                            field_name="bet_amount",
                            severity="ERROR",
                            recoverable=True,
                            user_feedback="Reduce the bet to keep balance above lower limit.",
                        )
                    if upper_limit > 0 and post_bet_balance >= upper_limit:
                        if strict_mode:
                            self._append_issue(
                                issues=issues,
                                code="POST_BET_AT_OR_ABOVE_UPPER_LIMIT",
                                message="Post-bet balance reaches upper limit in strict mode",
                                field_name="bet_amount",
                                severity="ERROR",
                                recoverable=True,
                                user_feedback="Adjust the bet to remain below upper limit.",
                            )
                        else:
                            self._append_issue(
                                issues=issues,
                                code="POST_BET_AT_OR_ABOVE_UPPER_LIMIT",
                                message="Post-bet balance reaches upper limit",
                                field_name="bet_amount",
                                severity="WARNING",
                                recoverable=True,
                                user_feedback="Consider adjusting the bet to stay below upper limit.",
                            )

        bet_snapshot = None
        if bet_id is not None:
            bet_snapshot = self._fetch_bet_snapshot(bet_id)
            checks["bet_reference_exists"] = bet_snapshot is not None
            if bet_snapshot is None:
                self._append_issue(
                    issues=issues,
                    code="BET_NOT_FOUND",
                    message="Bet reference not found",
                    field_name="bet_id",
                    severity="ERROR",
                    recoverable=True,
                    user_feedback="Use an existing bet id.",
                )
            else:
                ref_session_id = int(bet_snapshot.get("session_id") or 0)
                ref_gambler_id = int(bet_snapshot.get("gambler_id") or 0)
                checks["bet_reference_session_match"] = ref_session_id == session_id
                checks["bet_reference_gambler_match"] = ref_gambler_id == gambler_id
                if ref_session_id != session_id:
                    self._append_issue(
                        issues=issues,
                        code="BET_REFERENCE_SESSION_MISMATCH",
                        message="Bet reference session mismatch",
                        field_name="bet_id",
                        severity="ERROR",
                        recoverable=True,
                        user_feedback="Use a bet from the selected session.",
                    )
                if ref_gambler_id != gambler_id:
                    self._append_issue(
                        issues=issues,
                        code="BET_REFERENCE_GAMBLER_MISMATCH",
                        message="Bet reference gambler mismatch",
                        field_name="bet_id",
                        severity="ERROR",
                        recoverable=True,
                        user_feedback="Use a bet that belongs to the selected gambler.",
                    )

        unsettled_count = 0
        if session_snapshot is not None:
            unsettled_count = self._count_unsettled_bets(session_id=session_id)
            checks["unsettled_bets_count"] = unsettled_count
            if unsettled_count > 0:
                self._append_issue(
                    issues=issues,
                    code="UNSETTLED_BETS_PRESENT",
                    message="Session has unsettled bets",
                    field_name="session_id",
                    severity="WARNING",
                    recoverable=True,
                    user_feedback="Settle previous bets before placing more if needed.",
                )

        event_ids = self._persist_validation_events(
            scope="STAKE_BET_LIMITS",
            issues=issues,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=bet_id,
            inputs={
                "bet_amount": bet_amount,
                "win_probability": win_probability,
                "bet_id": bet_id,
            },
        )
        result = self._build_result(
            scope="STAKE_BET_LIMITS",
            issues=issues,
            checks=checks,
            context={
                "gambler_id": gambler_id,
                "session_id": session_id,
                "bet_id": bet_id,
                "input_bet_amount": bet_amount,
                "parsed_bet_amount": parsed_bet_amount,
                "input_win_probability": win_probability,
                "parsed_win_probability": parsed_probability,
                "gambler_snapshot": gambler_snapshot,
                "session_snapshot": session_snapshot,
                "session_parameters_snapshot": session_parameters_snapshot,
                "bet_snapshot": bet_snapshot,
                "unsettled_bets_count": unsettled_count,
            },
            event_ids=event_ids,
        )
        self._raise_if_requested(result, raise_on_error)
        return result

    def validate_input_bundle(
        self,
        gambler_id: int,
        session_id: int,
        stake_amount: Any,
        bet_amount: Any,
        win_probability: Any,
        bet_id: int | None = None,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        stake_result = self.validate_numeric_input(
            field_name="stake_amount",
            value=stake_amount,
            min_value=Decimal("0"),
            max_value=None,
            allow_zero=True,
            allow_none=False,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=bet_id,
            raise_on_error=False,
        )
        balance_result = self.validate_non_negative_balance(
            balance=stake_amount,
            gambler_id=gambler_id,
            session_id=session_id,
            raise_on_error=False,
        )
        limits_result = self.validate_stake_bet_limits(
            gambler_id=gambler_id,
            session_id=session_id,
            bet_amount=bet_amount,
            win_probability=win_probability,
            bet_id=bet_id,
            raise_on_error=False,
        )
        probability_result = self.validate_probability(
            probability=win_probability,
            gambler_id=gambler_id,
            session_id=session_id,
            bet_id=bet_id,
            raise_on_error=False,
        )

        combined_warnings = (
            stake_result.get("warnings", [])
            + balance_result.get("warnings", [])
            + limits_result.get("warnings", [])
            + probability_result.get("warnings", [])
        )
        combined_errors = (
            stake_result.get("errors", [])
            + balance_result.get("errors", [])
            + limits_result.get("errors", [])
            + probability_result.get("errors", [])
        )
        combined_feedback = (
            stake_result.get("recoverable_feedback_messages", [])
            + balance_result.get("recoverable_feedback_messages", [])
            + limits_result.get("recoverable_feedback_messages", [])
            + probability_result.get("recoverable_feedback_messages", [])
        )
        event_ids = (
            stake_result.get("event_ids", [])
            + balance_result.get("event_ids", [])
            + limits_result.get("event_ids", [])
            + probability_result.get("event_ids", [])
        )

        result = {
            "scope": "INPUT_BUNDLE",
            "valid": len(combined_errors) == 0,
            "classification": "ERROR" if combined_errors else ("WARNING" if combined_warnings else "OK"),
            "warnings": combined_warnings,
            "errors": combined_errors,
            "recoverable_feedback_messages": combined_feedback,
            "event_ids": event_ids,
            "results": {
                "stake": stake_result,
                "balance": balance_result,
                "limits": limits_result,
                "probability": probability_result,
            },
        }

        if raise_on_error and not result["valid"]:
            message = "; ".join(str(error.get("message", "Validation failed")) for error in combined_errors)
            if all(bool(error.get("recoverable", True)) for error in combined_errors):
                raise RecoverableValidationException(message=message, details={"result": result})
            raise ValidationException(message=message, recoverable=False, details={"result": result})

        return result
