from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import InvalidOperation
from enum import StrEnum

from duckdb import DuckDBPyConnection
from pydantic import BaseModel, ValidationError

from investment_journal.services.journal_service import JournalService
from shared.enums import AccountRole, ErrorType
from shared.models import BrokerTransaction, PortfolioCashSnapshot, PortfolioSnapshot

from ...transaction_reconciliation import (
    TransactionOverlapError,
    matched_other_source,
    require_compatible_economics,
)
from .api_mapping import (
    SchwabAccount,
    SchwabOrderStatus,
    account_snapshot,
    order_status,
    trade_record,
)
from .read_only import SchwabReadClient, SchwabReadError, utc_time


@dataclass(frozen=True)
class SchwabSyncResult:
    account: SchwabAccount
    positions: tuple[PortfolioSnapshot, ...]
    cash: PortfolioCashSnapshot | None
    transactions: tuple[BrokerTransaction, ...]
    orders: tuple[SchwabOrderStatus, ...]
    positions_inserted: int
    cash_inserted: int
    transactions_inserted: int
    skipped_positions: int


class SchwabSyncService:
    def __init__(self, db: DuckDBPyConnection, client: SchwabReadClient) -> None:
        self._db = db
        self._client = client

    def sync(
        self,
        account_id: str,
        *,
        start: datetime | None = None,
        orders: bool = False,
        as_of: datetime | None = None,
    ) -> SchwabSyncResult:
        end = utc_time(as_of) if as_of is not None else datetime.now(UTC)
        start = utc_time(start) if start is not None else None
        if orders and start is None:
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "读取订单时必须明确指定历史查询起点。"
            )
        if start is not None and not timedelta(seconds=1) <= end - start <= timedelta(
            days=365
        ):
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "历史查询区间应为 1 秒至 365 天。"
            )
        role = self._account_role(account_id)
        try:
            raw = self._client.read_account()
            observed = utc_time(as_of) if as_of is not None else datetime.now(UTC)
            account, positions, cash, skipped = account_snapshot(
                raw, account_id, role, observed
            )
            transactions = (
                self._history(account_id, start, end) if start is not None else ()
            )
            statuses = (
                self._orders(account_id, start, end)
                if orders and start is not None
                else ()
            )
        except (ValidationError, InvalidOperation, OverflowError):
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "Schwab 数据未通过规范字段或精度校验。"
            ) from None
        try:
            self._db.begin()
            try:
                self._account_role(account_id)
                # 写入阶段重新核对账户与交易来源，一批记录和成交日志一起提交。
                # 本批 API 中有对应 ID 的 CSV 记录会独立核对，不拦截其他同价同量的成交。
                incoming_ids = frozenset(
                    item.broker_transaction_id
                    for item in transactions
                    if item.broker_transaction_id is not None
                )
                trades_added = sum(
                    self._save_trade(item, incoming_ids) for item in transactions
                )
                positions_added = sum(
                    self._insert(
                        "portfolio_position_snapshot",
                        item,
                        exclude={"broker", "account_role"},
                    )
                    for item in positions
                )
                cash_added = int(
                    cash is not None and self._insert("portfolio_cash_snapshot", cash)
                )
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        except TransactionOverlapError as exc:
            raise SchwabReadError(ErrorType.RISK_RULE_BLOCKED, str(exc)) from None
        return SchwabSyncResult(
            account,
            positions,
            cash,
            transactions,
            statuses,
            positions_added,
            cash_added,
            trades_added,
            skipped,
        )

    def _account_role(self, account_id: str) -> AccountRole:
        row = self._db.execute(
            "SELECT broker, account_role, is_active, api_sync_enabled, base_currency "
            "FROM portfolio_account WHERE account_id = ?",
            [account_id],
        ).fetchone()
        expected = ("SCHWAB", AccountRole.ACTIVE_TRADING, True, True, "USD")
        if row != expected:
            raise SchwabReadError(
                ErrorType.RISK_RULE_BLOCKED,
                "仅可同步已启用 API 的 Schwab 主动交易美元账户。",
            )
        return AccountRole.ACTIVE_TRADING

    def _history(
        self, account_id: str, start: datetime, end: datetime
    ) -> tuple[BrokerTransaction, ...]:
        unique: dict[str, BrokerTransaction] = {}
        for row in self._client.read_trades(start, end):
            self._client.validate_account(row)
            item = trade_record(row, account_id, start, end)
            if item.transaction_id in unique and item != unique[item.transaction_id]:
                raise SchwabReadError(
                    ErrorType.VALIDATION_ERROR, "同一响应内的成交 ID 对应不同内容。"
                )
            unique[item.transaction_id] = item
        return tuple(unique.values())

    def _orders(
        self, account_id: str, start: datetime, end: datetime
    ) -> tuple[SchwabOrderStatus, ...]:
        results = []
        for row in self._client.read_orders(start, end):
            self._client.validate_account(row)
            item = order_status(row, account_id)
            if item.entered_at is not None and not start <= item.entered_at <= end:
                raise SchwabReadError(
                    ErrorType.VALIDATION_ERROR, "Schwab 订单不在所请求的历史区间。"
                )
            results.append(item)
        return tuple(results)

    def _save_trade(
        self, item: BrokerTransaction, incoming_ids: frozenset[str]
    ) -> bool:
        if matched_other_source(self._db, item, incoming_api_ids=incoming_ids):
            return False
        names = (
            "trade_date",
            "symbol",
            "transaction_type",
            "quantity",
            "price",
            "gross_amount",
            "fee",
            "net_amount",
        )
        row = self._db.execute(
            f"SELECT {', '.join(names)} FROM broker_transaction "
            "WHERE broker = 'SCHWAB' AND account_id = ? AND deduplication_key = ?",
            [item.account_id, item.deduplication_key],
        ).fetchone()
        if row is not None:
            require_compatible_economics(item, dict(zip(names, row, strict=True)))
            return False
        inserted = self._insert("broker_transaction", item)
        if (
            inserted
            and self._db.execute(
                "SELECT 1 FROM symbol WHERE symbol = ?", [item.symbol]
            ).fetchone()
        ):
            JournalService(self._db).record_transaction(item, in_transaction=True)
        return inserted

    def _insert(
        self,
        table: str,
        record: BaseModel,
        *,
        exclude: set[str] | frozenset[str] = frozenset(),
    ) -> bool:
        values = record.model_dump(exclude={"created_at", *exclude})
        key = "transaction_id" if table == "broker_transaction" else "snapshot_id"
        return (
            self._db.execute(
                f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)}) "
                f"ON CONFLICT DO NOTHING RETURNING {key}",
                [
                    value.value if isinstance(value, StrEnum) else value
                    for value in values.values()
                ],
            ).fetchone()
            is not None
        )
