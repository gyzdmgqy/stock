from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from duckdb import DuckDBPyConnection
from pydantic import Field, StrictBool, TypeAdapter

from shared.enums import AccountRole, Broker, IndividualStockPolicy
from shared.models import IntradaySignal
from shared.models._types import NonBlank, Price, SharedModel, UtcDatetime
from trade_planner.planners.base import (
    EntryPrices,
    NonNegativeMoney,
    NonNegativeShares,
    PortfolioState,
    RiskLimits,
)


class _AppSettings(SharedModel):
    name: NonBlank
    environment: NonBlank
    timezone: Literal["America/Chicago"]
    base_currency: Literal["USD"]
    report_format: list[Literal["markdown", "json"]]
    market_history_sessions: int = Field(default=220, ge=201, le=500)


class _AccountSettings(SharedModel):
    broker: Broker
    account_role: AccountRole
    individual_stock_policy: IndividualStockPolicy
    order_draft_enabled: StrictBool = False
    is_active: StrictBool = True


class _BrokerSettings(SharedModel):
    enabled: StrictBool
    order_draft_enabled: StrictBool = False


class PlanningReview(SharedModel):
    account_id: NonBlank
    symbol: NonBlank
    observed_at: UtcDatetime
    has_open_order: StrictBool | None = None
    available_to_sell: NonNegativeShares | None = None
    confirmed_flat: StrictBool = False
    account_equity: NonNegativeMoney | None = None
    combined_equity: NonNegativeMoney | None = None
    combined_symbol_value: NonNegativeMoney | None = None
    combined_sector_value: NonNegativeMoney | None = None
    reentry_candidate: StrictBool = False
    earnings_checked_through: date | None = None
    entry_prices: EntryPrices | None = None
    exit_limit_price: Price | None = None
    intraday_signal: IntradaySignal | None = None


@dataclass(frozen=True)
class PipelineConfig:
    app: _AppSettings
    limits: RiskLimits
    symbols: tuple[str, ...]
    accounts: dict[str, _AccountSettings]
    brokers: dict[Broker, _BrokerSettings]

    def drafts_enabled(self, account_id: str, account: "Account") -> bool:
        config = self.accounts[account_id]
        broker = self.brokers.get(account.broker)
        return bool(
            broker
            and broker.enabled
            and broker.order_draft_enabled
            and config.order_draft_enabled
            and account.order_draft_enabled
            and (config.broker, config.account_role, config.individual_stock_policy)
            == (account.broker, account.role, account.individual_stock_policy)
        )

    @classmethod
    def load(cls, config_dir: Path) -> "PipelineConfig":
        app = _AppSettings.model_validate(_yaml(config_dir / "app.yaml")["app"])
        if set(app.report_format) != {"markdown", "json"}:
            raise ValueError("每日流程要求 Markdown 和 JSON 两种简报格式。")
        limits = RiskLimits.model_validate(_yaml(config_dir / "risk.yaml")["risk"])
        lists = TypeAdapter(dict[NonBlank, list[NonBlank]]).validate_python(
            _yaml(config_dir / "symbols.yaml")
        )
        accounts = {
            account: _AccountSettings.model_validate(
                {
                    key: value
                    for key, value in row.items()
                    if key in _AccountSettings.model_fields
                }
            )
            for account, row in _yaml(config_dir / "accounts.yaml")["accounts"].items()
        }
        brokers = {
            Broker(name.upper()): _BrokerSettings.model_validate(
                {
                    key: value
                    for key, value in row.items()
                    if key in _BrokerSettings.model_fields
                }
            )
            for name, row in _yaml(config_dir / "broker.yaml")["brokers"].items()
        }
        symbols = tuple(
            dict.fromkeys(
                ticker.upper() for items in lists.values() for ticker in items
            )
        )
        return cls(app, limits, symbols, accounts, brokers)


def load_reviews(path: Path | None) -> dict[tuple[str, str], PlanningReview]:
    if path is None:
        return {}
    data = _yaml(path)
    if not isinstance(data, dict) or set(data) != {"reviews"}:
        raise ValueError("本地补充文件必须只含 reviews 列表。")
    reviews = TypeAdapter(list[PlanningReview]).validate_python(data["reviews"])
    indexed = {}
    for item in reviews:
        key = item.account_id, item.symbol.upper()
        if key in indexed:
            raise ValueError("本地补充文件不能重复确认同一账户和标的。")
        indexed[key] = item
    return indexed


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


@dataclass(frozen=True)
class Account:
    broker: Broker
    role: AccountRole
    individual_stock_policy: IndividualStockPolicy | None
    order_draft_enabled: bool


@dataclass(frozen=True)
class Position:
    quantity: Decimal | None
    market_value: Decimal | None
    observed_at: datetime


class PortfolioInputs:
    def __init__(
        self, db: DuckDBPyConnection, config: PipelineConfig, day: date, as_of: datetime
    ) -> None:
        self.as_of = as_of
        self.max_age = timedelta(hours=config.limits.max_portfolio_age_hours)
        self.warnings: list[str] = []
        rows = db.execute(
            "SELECT account_id, broker, account_role, individual_stock_policy, order_draft_enabled, "
            "base_currency FROM portfolio_account WHERE is_active ORDER BY account_id"
        ).fetchall()
        self.accounts = {
            key: Account(
                Broker(broker),
                AccountRole(role),
                IndividualStockPolicy(policy) if policy else None,
                enabled is True,
            )
            for key, broker, role, policy, enabled, currency in rows
            if key in config.accounts
            and config.accounts[key].is_active
            and currency == "USD"
        }
        for key, setting in config.accounts.items():
            if setting.is_active and key not in self.accounts:
                self.warnings.append(f"{key}：没有已启用的 USD 账户配置。")
        self.positions = {
            (account, symbol): Position(quantity, value, observed_at)
            for account, symbol, quantity, value, observed_at in db.execute(
                """
                SELECT account_id, symbol, TRY_CAST(quantity AS DECIMAL(20, 8)),
                    TRY_CAST(market_value AS DECIMAL(20, 6)), observed_at
                FROM portfolio_position_snapshot
                WHERE snapshot_date <= ? AND observed_at <= ?
                QUALIFY row_number() OVER (PARTITION BY account_id, symbol
                    ORDER BY observed_at DESC, created_at DESC NULLS LAST, snapshot_id DESC) = 1
                ORDER BY account_id, symbol
                """,
                [day, as_of],
            ).fetchall()
            if account in self.accounts
        }
        self.cash = {
            account: (value, observed_at)
            for account, value, observed_at in db.execute(
                """
                SELECT account_id, available_to_trade, observed_at FROM portfolio_cash_snapshot
                WHERE currency = 'USD' AND snapshot_date <= ? AND observed_at <= ?
                QUALIFY row_number() OVER (PARTITION BY account_id
                    ORDER BY observed_at DESC, created_at DESC NULLS LAST, snapshot_id DESC) = 1
                """,
                [day, as_of],
            ).fetchall()
        }
        self.net_value = {
            account: value
            for account, value in db.execute(
                """
                SELECT account_id, TRY_CAST(total_market_value AS DECIMAL(20, 6))
                FROM portfolio_risk_snapshot WHERE snapshot_date = ? AND created_at <= ?
                QUALIFY row_number() OVER (PARTITION BY account_id
                    ORDER BY created_at DESC, snapshot_id DESC) = 1
                """,
                [day, as_of],
            ).fetchall()
            if value is not None and value >= 0
        }
        self.combined_equity = self.net_value.get(None)
        if (
            self.combined_equity is None
            and rows
            and all(
                currency == "USD" and key in self.net_value
                for key, *_, currency in rows
            )
        ):
            self.combined_equity = sum(
                (self.net_value[row[0]] for row in rows), Decimal(0)
            )
        self.live_order_pairs = set(
            db.execute(
                "SELECT DISTINCT account_id, symbol FROM order_draft WHERE status IN "
                "('SUBMITTING', 'SUBMITTED', 'PARTIALLY_FILLED', 'UNKNOWN')"
            ).fetchall()
        )
        for account in self.accounts:
            if account not in self.net_value:
                self.warnings.append(f"{account}：缺少当日净值快照。")
            if self._available_cash(account)[0] is None:
                self.warnings.append(f"{account}：缺少有效的可交易现金快照。")

    def held_symbols(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                symbol
                for (_, symbol), position in self.positions.items()
                if position.quantity is not None and position.quantity > 0
            )
        )

    def for_symbol(
        self, account_id: str, symbol: str, review: PlanningReview | None
    ) -> tuple[PortfolioState | None, PlanningReview | None, str | None]:
        position = self.positions.get((account_id, symbol))
        label = f"{account_id}/{symbol}"
        if position is not None and not self._fresh(position.observed_at):
            return None, None, f"{label}：导入的持仓已过期。"
        if review is not None and (
            not self._fresh(review.observed_at)
            or position is not None
            and review.observed_at < position.observed_at
        ):
            review = None
        if position is None:
            if review is None or not review.confirmed_flat:
                return None, None, f"{label}：缺少明确的持仓或空仓确认。"
            position = Position(Decimal(0), Decimal(0), review.observed_at)
        if position.quantity is None or position.quantity < 0:
            return None, None, f"{label}：持仓股数未知或不受首版支持。"
        if review and (
            (review.confirmed_flat and position.quantity != 0)
            or (
                review.available_to_sell is not None
                and review.available_to_sell > position.quantity
            )
        ):
            return None, None, f"{label}：人工确认与导入持仓冲突。"

        cash, cash_time = self._available_cash(account_id)
        observed_at = min(
            instant
            for instant in (
                position.observed_at,
                review.observed_at if review else None,
                cash_time,
            )
            if instant is not None
        )
        equity = (
            self.net_value.get(account_id)
            if account_id in self.net_value
            else review.account_equity if review else None
        )
        combined = (
            self.combined_equity
            if self.combined_equity is not None
            else review.combined_equity if review else None
        )
        market_value = position.market_value
        if market_value is not None and (
            market_value < 0 or (position.quantity == 0) != (market_value == 0)
        ):
            market_value = None
        has_open_order = (
            True
            if (account_id, symbol) in self.live_order_pairs
            else review.has_open_order if review else None
        )
        sellable = review.available_to_sell if review else None
        state = PortfolioState(
            account_id=account_id,
            symbol=symbol,
            observed_at=observed_at,
            account_equity=equity,
            available_cash=cash,
            quantity=position.quantity,
            position_value=market_value,
            available_to_sell=sellable,
            has_open_order=has_open_order,
            combined_equity=combined,
            combined_symbol_value=review.combined_symbol_value if review else None,
            combined_sector_value=review.combined_sector_value if review else None,
        )
        warning = None
        if self.accounts[account_id].role is AccountRole.ACTIVE_TRADING and (
            has_open_order is None or (position.quantity > 0 and sellable is None)
        ):
            warning = f"{label}：缺少有效的挂单状态或可卖股数确认。"
        return state, review, warning

    def _fresh(self, at: datetime) -> bool:
        return timedelta(0) <= self.as_of - at <= self.max_age

    def _available_cash(
        self, account_id: str
    ) -> tuple[Decimal | None, datetime | None]:
        row = self.cash.get(account_id)
        if row is None or row[0] is None or row[0] < 0 or not self._fresh(row[1]):
            return None, None
        return row
