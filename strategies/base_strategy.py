from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Mapping


class BettingStrategy(ABC):
    strategy_code: str

    @abstractmethod
    def propose_bet_amount(
        self,
        current_stake: Decimal,
        requested_amount: Decimal | None,
        last_bet_amount: Decimal | None,
        last_outcome: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Decimal:
        raise NotImplementedError
