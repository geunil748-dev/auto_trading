from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceBar:
    close: float
    high: float
    low: float

    def __post_init__(self) -> None:
        if min(self.close, self.high, self.low) <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < self.low:
            raise ValueError("bar high cannot be below low")
