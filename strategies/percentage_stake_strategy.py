from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from strategies.base_strategy import BettingStrategy


class PercentageStakeStrategy(BettingStrategy):
    strategy_code = "PERCENTAGE"

    def propose_bet_amount(
        self,
        current_stake: Decimal,
        requested_amount: Decimal | None,
        last_bet_amount: Decimal | None,
        last_outcome: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Decimal:
        if requested_amount is not None:
            return requested_amount

        data = metadata or {}
        percentage = Decimal(str(data.get("percentage", "0.05")))
        if percentage <= 0:
            return Decimal("0")
        return current_stake * percentage
