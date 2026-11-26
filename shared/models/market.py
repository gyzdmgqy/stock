from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ._types import NonBlank, NonNegativeInt, TimestampedModel, UtcDatetime

MarketPrice = Annotated[float, Field(gt=0, strict=True)]


class _PriceBar(TimestampedModel):
    symbol: NonBlank
    trade_date: date
    open: MarketPrice | None = None
    high: MarketPrice | None = None
    low: MarketPrice | None = None
    close: MarketPrice | None = None
    volume: NonNegativeInt | None = None
    source: NonBlank | None = None

    @model_validator(mode="after")
    def validate_price_range(self) -> Self:
        for price in (self.low, self.open, self.close):
            if self.high is not None and price is not None and price > self.high:
                raise ValueError("最低价、开盘价和收盘价不能高于最高价")
        for price in (self.open, self.close):
            if self.low is not None and price is not None and price < self.low:
                raise ValueError("开盘价和收盘价不能低于最低价")
        return self


class DailyPrice(_PriceBar):
    adjusted_close: MarketPrice | None = None


class IntradayPrice(_PriceBar):
    interval: Literal["1h"] = "1h"
    bar_start: UtcDatetime
