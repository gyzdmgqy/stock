from datetime import date
from typing import Annotated

from pydantic import Field

from shared.enums import OutcomeLabel, ReviewType, StrategyType
from shared.models._types import MutableRecord, NonBlank, TimestampedModel

Count = Annotated[int, Field(ge=0)]


class TradeOutcome(MutableRecord):
    outcome_id: NonBlank
    plan_id: NonBlank | None = None
    draft_id: NonBlank | None = None
    transaction_id: NonBlank | None = None
    symbol: NonBlank
    account_id: NonBlank | None = None
    reference_date: date
    reference_price: float = Field(gt=0)
    outcome_date_5d: date | None = None
    outcome_price_5d: float | None = None
    outcome_return_5d: float | None = None
    max_drawdown_5d: float | None = None
    max_runup_5d: float | None = None
    outcome_date_20d: date | None = None
    outcome_price_20d: float | None = None
    outcome_return_20d: float | None = None
    max_drawdown_20d: float | None = None
    max_runup_20d: float | None = None
    outcome_date_60d: date | None = None
    outcome_price_60d: float | None = None
    outcome_return_60d: float | None = None
    max_drawdown_60d: float | None = None
    max_runup_60d: float | None = None
    outcome_label: OutcomeLabel | None = None
    lesson: str | None = None


class PerformanceReview(TimestampedModel):
    review_id: NonBlank
    review_date: date
    review_type: ReviewType
    strategy_type: StrategyType | None = None
    account_id: NonBlank | None = None
    period_start: date
    period_end: date
    trade_count: Count = 0
    plan_count: Count = 0
    approved_count: Count = 0
    rejected_count: Count = 0
    win_rate: float | None = None
    average_return: float | None = None
    median_return: float | None = None
    max_drawdown: float | None = None
    average_risk_reward: float | None = None
    best_trade_symbol: NonBlank | None = None
    worst_trade_symbol: NonBlank | None = None
    summary: str | None = None
    lessons: str | None = None
    next_actions: str | None = None
