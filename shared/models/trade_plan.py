from datetime import date
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from shared.enums import (
    AccountRole,
    Action,
    OrderType,
    StopType,
    StrategyType,
    TradePlanStatus,
)

from ._types import (
    Fraction,
    MutableRecord,
    NonBlank,
    PositiveShares,
    Price,
    Score,
    SharedModel,
)


class EntryOrder(SharedModel):
    type: OrderType
    price: Price | None = None

    @model_validator(mode="after")
    def validate_limit_price(self) -> Self:
        if self.type is OrderType.LIMIT and self.price is None:
            raise ValueError("限价入场必须填写价格")
        return self


class StopOrder(SharedModel):
    type: StopType
    stop_price: Price | None = None
    limit_price: Price | None = None
    condition: NonBlank | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_stop_fields(self) -> Self:
        if (
            self.type in (StopType.PRICE_STOP, StopType.STOP_LIMIT)
            and self.stop_price is None
        ):
            raise ValueError("价格止损必须填写触发价")
        if self.type is StopType.STOP_LIMIT and self.limit_price is None:
            raise ValueError("止损限价计划必须填写限价")
        if (
            self.type in (StopType.STRUCTURE_CONFIRMATION, StopType.TIME_STOP)
            and self.condition is None
        ):
            raise ValueError("结构确认和时间止损必须填写触发条件")
        return self


class PositionSize(SharedModel):
    percent_of_portfolio: Score | None = None
    estimated_value: Price | None = None
    quantity: PositiveShares | None = None
    sizing_basis: Literal["ACCOUNT"] = "ACCOUNT"
    sizing_base_value: Price | None = None


class TradePlan(MutableRecord):
    plan_id: NonBlank
    symbol: NonBlank
    plan_date: date
    account_id: NonBlank
    account_role: AccountRole
    supersedes_plan_id: NonBlank | None = None
    primary_timeframe: NonBlank = "daily"
    execution_timeframe: NonBlank | None = None
    rule_version: NonBlank | None = None
    input_references: JsonValue = None
    action: Action
    strategy_type: StrategyType | None = None
    thesis: str | None = None
    reason: str | None = None
    entry_condition: list[NonBlank] = Field(default_factory=list)
    entry_order: EntryOrder | None = None
    stop_order: StopOrder | None = None
    target_price_1: Price | None = None
    target_price_2: Price | None = None
    position_size: PositionSize | None = None
    risk_reward_ratio: float | None = Field(default=None, ge=0)
    confidence: Score | None = None
    invalid_condition: list[NonBlank] = Field(default_factory=list)
    exit_trigger: list[NonBlank] = Field(default_factory=list)
    replacement: dict[NonBlank, Fraction] | None = None
    future_reentry_account: NonBlank | None = None
    status: TradePlanStatus = Field(default=TradePlanStatus.DRAFT, frozen=True)

    @model_validator(mode="after")
    def validate_plan_conditions(self) -> Self:
        if (
            self.action in (Action.ADD, Action.RE_ENTRY, Action.REDUCE, Action.EXIT)
            and not self.invalid_condition
        ):
            raise ValueError("可执行计划必须包含失效条件")
        if self.action is Action.EXIT_ONLY and not self.exit_trigger:
            raise ValueError("条件退出计划必须包含退出触发条件")
        return self

    def transition_to(self, target: TradePlanStatus | str) -> Self:
        status = TradePlanStatus(target)
        if not self.status.allows(status):
            raise ValueError(f"交易计划不能从 {self.status} 转为 {status}")
        return type(self).model_validate({**self.model_dump(), "status": status})
