from __future__ import annotations

from typing import Any

from services.stake_management_service import StakeManagementService


class StakeHistoryReport:
    def __init__(self, stake_management_service: StakeManagementService):
        self.stake_management_service = stake_management_service

    def real_time_balance(self, gambler_id: int, session_id: int | None = None) -> dict[str, Any]:
        return self.stake_management_service.get_real_time_balance(gambler_id=gambler_id, session_id=session_id)

    def peak_lowest_stake(self, session_id: int) -> dict[str, Any]:
        return self.stake_management_service.get_peak_lowest_stake(session_id=session_id)

    def volatility_and_transaction_summaries(self, session_id: int) -> dict[str, Any]:
        return self.stake_management_service.summarize_transactions(session_id=session_id)

    def stake_history(self, session_id: int, limit: int | None = 200) -> list[dict[str, Any]]:
        return self.stake_management_service.get_stake_history(session_id=session_id, limit=limit)

    def full_report(self, gambler_id: int, session_id: int, limit: int | None = 200) -> dict[str, Any]:
        return {
            "real_time_balance": self.real_time_balance(gambler_id=gambler_id, session_id=session_id),
            "peak_lowest_stake": self.peak_lowest_stake(session_id=session_id),
            "volatility_and_transaction_summaries": self.volatility_and_transaction_summaries(session_id=session_id),
            "stake_history": self.stake_history(session_id=session_id, limit=limit),
        }
