from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from strategies.base_strategy import BettingStrategy


class FixedStakeStrategy(BettingStrategy):
    strategy_code = "FIXED"

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
        if metadata and metadata.get("default_amount") is not None:
            return Decimal(str(metadata.get("default_amount")))
        return Decimal("0")
