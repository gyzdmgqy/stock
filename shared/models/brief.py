from datetime import date

from pydantic import Field, JsonValue

from shared.enums import Action, MarketRegime, OrderDraftStatus, TradePlanStatus

from ._types import Money, NonBlank, Score, SharedModel, TimestampedModel


class MarketSummary(SharedModel):
    market_regime: MarketRegime | None = None
    confidence: Score | None = None
    key_points: list[NonBlank] = Field(default_factory=list)


class PortfolioSummary(SharedModel):
    total_value: Money | None = None
    core_passive_value: Money | None = None
    active_trading_value: Money | None = None
    key_positions: list[dict[str, JsonValue]] = Field(default_factory=list)


class RiskSummary(SharedModel):
    risk_level: NonBlank | None = None
    key_risks: list[NonBlank] = Field(default_factory=list)


class TradePlanSummary(SharedModel):
    plan_id: NonBlank
    symbol: NonBlank
    action: Action
    confidence: Score | None = None
    account_id: NonBlank | None = None
    status: TradePlanStatus | None = None


class OrderDraftSummary(SharedModel):
    draft_id: NonBlank
    symbol: NonBlank
    status: OrderDraftStatus
    account_id: NonBlank | None = None
    plan_id: NonBlank | None = None


class DailyCioBrief(TimestampedModel):
    brief_id: NonBlank
    brief_date: date
    market_summary: MarketSummary | None = None
    portfolio_summary: PortfolioSummary | None = None
    risk_summary: RiskSummary | None = None
    trade_plan_summary: list[TradePlanSummary] = Field(default_factory=list)
    order_draft_summary: list[OrderDraftSummary] = Field(default_factory=list)
    final_recommendation: str | None = None
    markdown_path: NonBlank | None = None
    journal_reminders: list[NonBlank] = Field(default_factory=list)
