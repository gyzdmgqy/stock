from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from shared.enums import (
    AccountRole,
    Action,
    Broker,
    IndividualStockPolicy,
    OrderInstruction,
    OrderType,
    StrategyType,
    TimeInForce,
)
from shared.models import DailySignal, IntradaySignal, TradePlan
from shared.models._types import (
    Fraction,
    Money,
    NonBlank,
    PositiveShares,
    Price,
    Score,
    ShareAmount,
    SharedModel,
    UtcDatetime,
)
from shared.models.trade_plan import EntryOrder, PositionSize, StopOrder

AssetType = Literal["STOCK", "ETF", "INDEX", "CASH"]
NonNegativeMoney = Annotated[Money, Field(ge=0)]
NonNegativeShares = Annotated[ShareAmount, Field(ge=0)]


class RiskLimits(SharedModel):
    max_single_stock_weight: Decimal = Field(default=Decimal("0.08"), gt=0, le=1)
    max_new_trade_weight: Decimal = Field(default=Decimal("0.03"), gt=0, le=1)
    max_trade_risk_percent: Decimal = Field(default=Decimal("0.005"), gt=0, le=1)
    max_combined_symbol_weight: Decimal = Field(default=Decimal("0.08"), gt=0, le=1)
    max_combined_sector_weight: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    min_risk_reward_ratio: Decimal = Field(default=Decimal("2"), gt=0)
    block_new_entry_before_earnings_days: int = Field(default=5, ge=0)
    min_entry_confidence_for_order_draft: Score = 70
    max_hourly_age_minutes: int = Field(default=120, gt=0)
    max_portfolio_age_hours: int = Field(default=24, gt=0)


class AccountPolicy(SharedModel):
    account_id: NonBlank
    broker: Broker
    account_role: AccountRole
    individual_stock_policy: IndividualStockPolicy | None
    order_draft_enabled: bool
    is_active: bool
    base_currency: str
    default_replacement: dict[NonBlank, Fraction] | None = None

    @model_validator(mode="after")
    def validate_replacement(self) -> Self:
        if self.default_replacement is not None and (
            not self.default_replacement
            or abs(sum(self.default_replacement.values()) - 1) > 1e-9
        ):
            raise ValueError("置换配置的权重之和必须为 1")
        return self


class PortfolioState(SharedModel):
    account_id: NonBlank
    symbol: NonBlank
    observed_at: UtcDatetime
    account_equity: NonNegativeMoney | None = None
    available_cash: NonNegativeMoney | None = None
    quantity: NonNegativeShares
    position_value: NonNegativeMoney | None = None
    available_to_sell: NonNegativeShares | None = None
    has_open_order: StrictBool | None = None
    combined_equity: NonNegativeMoney | None = None
    combined_symbol_value: NonNegativeMoney | None = None
    combined_sector_value: NonNegativeMoney | None = None

    @model_validator(mode="after")
    def validate_holdings(self) -> Self:
        if self.position_value is not None and (
            (self.quantity == 0) != (self.position_value == 0)
        ):
            raise ValueError("持仓股数与市值不一致")
        if (
            self.available_to_sell is not None
            and self.available_to_sell > self.quantity
        ):
            raise ValueError("可卖股数不能超过所持股数")
        return self


class EntryPrices(SharedModel):
    limit_price: Price
    stop_price: Price
    target_price: Price

    @model_validator(mode="after")
    def validate_levels(self) -> Self:
        if not self.stop_price < self.limit_price < self.target_price:
            raise ValueError("做多计划须满足止损参考价 < 限价 < 目标价")
        return self

    @property
    def risk_reward(self) -> Decimal:
        return (self.target_price - self.limit_price) / (
            self.limit_price - self.stop_price
        )


class PlanningRequest(SharedModel):
    account_id: NonBlank
    signal_id: NonBlank
    as_of: UtcDatetime
    session_close: UtcDatetime | None = None
    trading_sessions: tuple[date, ...] = ()
    portfolio: PortfolioState | None = None
    intraday_signal: IntradaySignal | None = None
    earnings_checked_through: date | None = None
    entry_prices: EntryPrices | None = None
    exit_limit_price: Price | None = None
    reentry_candidate: StrictBool = False

    @model_validator(mode="after")
    def validate_sessions(self) -> Self:
        if tuple(sorted(set(self.trading_sessions))) != self.trading_sessions:
            raise ValueError("交易日历必须升序排列且无重复日期")
        return self


@dataclass(frozen=True)
class PlanningContext:
    request: PlanningRequest
    account: AccountPolicy
    signal: DailySignal
    plan_date: date
    asset_type: AssetType | None
    daily_is_current: bool
    earnings_dates: tuple[date, ...]
    confirmed_ma200_exit: bool
    future_reentry_account: str | None
    limits: RiskLimits


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    strategy_type: StrategyType | None = None
    confidence: float | None = None
    entry_condition: tuple[str, ...] = ()
    invalid_condition: tuple[str, ...] = ()
    exit_trigger: tuple[str, ...] = ()
    order: EntryOrder | None = None
    stop: StopOrder | None = None
    position_size: PositionSize | None = None
    target_price: Decimal | None = None
    risk_reward_ratio: float | None = None
    replacement: dict[str, float] | None = None
    future_reentry_account: str | None = None
    requires_hourly: bool = False


class OrderIntent(SharedModel):
    plan_id: NonBlank
    account_id: NonBlank
    symbol: NonBlank
    instruction: OrderInstruction
    order_type: Literal[OrderType.LIMIT] = OrderType.LIMIT
    quantity: PositiveShares
    limit_price: Price
    time_in_force: TimeInForce = TimeInForce.DAY


@dataclass(frozen=True)
class PlanningResult:
    plan: TradePlan
    order_intent: OrderIntent | None
