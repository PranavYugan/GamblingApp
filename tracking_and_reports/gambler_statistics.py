from __future__ import annotations

from typing import Any

from services.gambler_profile_service import GamblerProfileService


class GamblerStatistics:
    def __init__(self, gambler_profile_service: GamblerProfileService):
        self.gambler_profile_service = gambler_profile_service

    def current_financial_status(self, gambler_id: int) -> dict[str, Any]:
        return self.gambler_profile_service.get_current_financial_status(gambler_id)

    def profile_summary(self, gambler_id: int) -> dict[str, Any]:
        return self.gambler_profile_service.get_profile_summary(gambler_id)

    def eligibility_status(self, gambler_id: int, proposed_bet: Any | None = None) -> dict[str, Any]:
        return self.gambler_profile_service.validate_eligibility(gambler_id, proposed_bet)

    def uc01_report(self, gambler_id: int, proposed_bet: Any | None = None) -> dict[str, Any]:
        return {
            "current_financial_status": self.current_financial_status(gambler_id),
            "profile_summary": self.profile_summary(gambler_id),
            "eligibility_status": self.eligibility_status(gambler_id, proposed_bet),
        }
