from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from strategies.base_strategy import BettingStrategy


class MartingaleStrategy(BettingStrategy):
    strategy_code = "MARTINGALE"

    def propose_bet_amount(
        self,
        current_stake: Decimal,
        requested_amount: Decimal | None,
        last_bet_amount: Decimal | None,
        last_outcome: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Decimal:
        data = metadata or {}
        base_amount = requested_amount if requested_amount is not None else Decimal(str(data.get("base_amount", "0")))
        multiplier = Decimal(str(data.get("multiplier", "2")))

        if (last_outcome or "").upper() == "LOSS" and last_bet_amount is not None and last_bet_amount > 0:
            return last_bet_amount * multiplier

        return base_amount
