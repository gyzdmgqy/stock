from datetime import date
from typing import Literal

from shared.enums import (
    Action,
    GapDirection,
    GapType,
    IntradayActionHint,
    MarketRegime,
    PriceLocation,
    TrendState,
)

from ._types import NonBlank, Score, TimestampedModel, UtcDatetime


class DailySignal(TimestampedModel):
    signal_id: NonBlank
    symbol: NonBlank
    trade_date: date
    market_regime: MarketRegime | None = None
    trend_state: TrendState | None = None
    price_location: PriceLocation | None = None
    gap_type: GapType | None = None
    gap_direction: GapDirection | None = None
    gap_percent: float | None = None
    false_breakdown_score: Score | None = None
    volume_confirmation_score: Score | None = None
    risk_score: Score | None = None
    action_hint: Action | None = None
    confidence: Score | None = None
    reason: str | None = None


class IntradaySignal(TimestampedModel):
    signal_id: NonBlank
    symbol: NonBlank
    trade_date: date
    bar_start: UtcDatetime
    interval: Literal["1h"] = "1h"
    vwap_status: NonBlank | None = None
    hourly_trend: NonBlank | None = None
    intraday_recovery_score: Score | None = None
    execution_quality_score: Score | None = None
    action_hint: IntradayActionHint | None = None
    reason: str | None = None
