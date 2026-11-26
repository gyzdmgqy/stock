from datetime import date

from shared.enums import (
    AccountRole,
    Broker,
    OrderType,
    TransactionSource,
    TransactionType,
)

from ._types import (
    Fraction,
    Money,
    NonBlank,
    Price,
    ShareAmount,
    TimestampedModel,
    UtcDatetime,
)


class PortfolioSnapshot(TimestampedModel):
    snapshot_id: NonBlank
    account_id: NonBlank
    broker: Broker
    account_role: AccountRole
    snapshot_date: date
    symbol: NonBlank
    observed_at: UtcDatetime | None = None
    source: TransactionSource | None = None
    quantity: ShareAmount | None = None
    market_price: Price | None = None
    market_value: Money | None = None
    cost_basis: Money | None = None
    unrealized_pnl: Money | None = None
    unrealized_pnl_percent: float | None = None
    portfolio_weight: Fraction | None = None


class BrokerTransaction(TimestampedModel):
    transaction_id: NonBlank
    broker: Broker
    account_id: NonBlank
    symbol: NonBlank | None = None
    transaction_time: UtcDatetime | None = None
    trade_date: date | None = None
    settlement_date: date | None = None
    transaction_type: TransactionType
    quantity: ShareAmount | None = None
    price: Price | None = None
    gross_amount: Money | None = None
    fee: Money | None = None
    net_amount: Money | None = None
    order_type: OrderType | None = None
    broker_order_id: NonBlank | None = None
    broker_transaction_id: NonBlank | None = None
    plan_id: NonBlank | None = None
    draft_id: NonBlank | None = None
    source: TransactionSource
    source_file: NonBlank | None = None
    deduplication_key: NonBlank | None = None
    note: str | None = None
