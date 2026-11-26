from datetime import date

from ._types import NonBlank, TimestampedModel


class DailyIndicator(TimestampedModel):
    symbol: NonBlank
    trade_date: date
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma30: float | None = None
    ma50: float | None = None
    ma100: float | None = None
    ma200: float | None = None
    atr14: float | None = None
    rsi14: float | None = None
    volume_avg5: float | None = None
    volume_avg20: float | None = None
    volume_ratio_5: float | None = None
    volume_ratio_20: float | None = None
