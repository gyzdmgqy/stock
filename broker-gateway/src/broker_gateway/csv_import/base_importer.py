import csv
import io
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from shared.enums import ErrorType, OrderType, TransactionSource, TransactionType
from shared.models import BrokerTransaction, PortfolioSnapshot

from ..adapters.csv_format import CASH, CsvFormat, Section, label
from .normalizer import Account, digest, record_id, snapshot_date
from .validators import (
    CsvImportError,
    number,
    optional,
    percent,
    session_date,
    symbol,
    timestamp,
    validation,
)

EXECUTIONS = {TransactionType.BUY, TransactionType.SELL}


def read_rows(data: bytes, transactions: CsvFormat, positions: CsvFormat):
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError(
            ErrorType.CSV_PARSE_ERROR, "CSV 必须使用 UTF-8 编码。"
        ) from exc

    reader = csv.reader(io.StringIO(raw, newline=""), strict=True)
    seen: set[Section] = set()
    active = None
    header_size = 0
    try:
        for cells in reader:
            row = reader.line_num
            if not any(cell.strip() for cell in cells):
                continue
            for schema in (transactions, positions, CASH):
                columns = schema.columns(cells)
                if not schema.required <= columns.keys():
                    continue
                if (
                    schema is CASH
                    and not {"cash_balance", "available_to_trade"} & columns.keys()
                ):
                    continue
                if schema.section in seen:
                    raise validation("检测到重复数据段，可能包含多个账户。", row)
                seen.add(schema.section)
                active = schema.section, columns
                header_size = len(cells)
                break
            else:
                if active is None:
                    if any(
                        label(cell) in {"all accounts", "all brokerage accounts"}
                        for cell in cells
                    ):
                        raise validation("请导出单个账户，不能导入合并账户。", row)
                    continue
                if any(cell.strip() for cell in cells[header_size:]):
                    raise CsvImportError(
                        ErrorType.CSV_PARSE_ERROR, "列数超过表头。", row=row
                    )
                section, columns = active
                fields = {}
                for field, indices in columns.items():
                    values = {
                        cells[idx].strip()
                        for idx in indices
                        if idx < len(cells) and optional(cells[idx]) is not None
                    }
                    if len(values) > 1:
                        raise validation(f"{field} 的对应列有冲突。", row)
                    fields[field] = next(iter(values), "")
                yield section, row, fields
    except csv.Error as exc:
        raise CsvImportError(
            ErrorType.CSV_PARSE_ERROR, "CSV 引号或字段格式无效。", row=reader.line_num
        ) from exc
    if not seen:
        raise CsvImportError(ErrorType.CSV_PARSE_ERROR, "未找到受支持的 CSV 表头。")


def transaction_facts(transaction: BrokerTransaction) -> dict:
    fields = transaction.model_dump(
        exclude={
            "transaction_id",
            "broker",
            "account_id",
            "source",
            "source_file",
            "created_at",
            "broker_transaction_id",
            "plan_id",
            "draft_id",
            "deduplication_key",
        }
    )
    if transaction.transaction_type is not TransactionType.OTHER:
        fields.pop("note")
    return fields


class TransactionNormalizer:
    def __init__(
        self, account: Account, source_file: str, types: dict[str, TransactionType]
    ) -> None:
        self.account = account
        self.source_file = source_file
        self.types = types
        self.occurrences: Counter[str] = Counter()

    def normalize(self, fields: dict[str, str], row: int) -> BrokerTransaction:
        try:
            return self._normalize(fields, row)
        except (ValidationError, InvalidOperation) as exc:
            raise validation("交易字段超出有效范围或精度。", row) from exc

    def _normalize(self, fields: dict[str, str], row: int) -> BrokerTransaction:
        action = label(fields["action"])
        if not action:
            raise validation("缺少交易类型。", row)
        if action in {"buy to open", "buy to close", "sell to open", "sell to close"}:
            raise validation("首版不支持期权成交。", row)
        transaction_type = self.types.get(action, TransactionType.OTHER)
        trade_date = session_date(fields["trade_date"], "trade_date", row)
        if trade_date is None:
            raise validation("缺少交易日期。", row)
        ticker = symbol(fields["symbol"], row)
        quantity = number(fields.get("quantity", ""), "quantity", row)
        price = number(fields.get("price", ""), "price", row)
        gross = number(fields.get("gross_amount", ""), "gross_amount", row)
        fee = number(fields.get("fee", ""), "fee", row)
        net = number(fields.get("net_amount", ""), "net_amount", row)
        if transaction_type in EXECUTIONS:
            if ticker is None or not quantity or price is None or price <= 0:
                raise validation("成交必须有标的、非零数量和正数价格。", row)
            if net is not None and (
                (transaction_type is TransactionType.BUY and net > 0)
                or (transaction_type is TransactionType.SELL and net < 0)
            ):
                raise validation("成交净额方向与买卖类型不一致。", row)
            if gross is None:
                gross = (abs(quantity) * price).quantize(Decimal("0.000001"))
        # 有些非成交记录用零股价占位；不能把它当作成交价。
        order_type = optional(fields.get("order_type", ""))
        if order_type is not None:
            order_type = order_type.upper().replace(" ", "_")
            if order_type not in OrderType:
                raise validation("订单类型不在规范枚举中。", row)
        execution_id = optional(fields.get("broker_transaction_id", ""))
        account = self.account
        draft = BrokerTransaction(
            transaction_id="pending",
            account_id=account.account_id,
            broker=account.broker,
            source=TransactionSource.CSV,
            source_file=self.source_file,
            transaction_type=transaction_type,
            symbol=ticker,
            trade_date=trade_date,
            settlement_date=session_date(
                fields.get("settlement_date", ""), "settlement_date", row
            ),
            transaction_time=timestamp(
                fields.get("transaction_time", ""), "transaction_time", row
            ),
            quantity=(
                abs(quantity)
                if quantity is not None and transaction_type in EXECUTIONS
                else quantity
            ),
            price=price if price != 0 else None,
            gross_amount=abs(gross) if gross is not None else None,
            fee=abs(fee) if fee is not None else None,
            net_amount=net,
            order_type=order_type,
            broker_order_id=optional(fields.get("broker_order_id", "")),
            broker_transaction_id=execution_id,
            note=action if transaction_type is TransactionType.OTHER else None,
        )
        if execution_id:
            key = f"broker-id:{digest(execution_id)}"
        else:
            fingerprint = digest(transaction_facts(draft))
            self.occurrences[fingerprint] += 1
            key = f"csv:v1:{fingerprint}:{self.occurrences[fingerprint]}"
        draft.deduplication_key = key
        draft.transaction_id = record_id("TXN", account.account_id, account.broker, key)
        return draft


def normalize_position(
    fields: dict[str, str], row: int, account: Account, observed_at: datetime
) -> PortfolioSnapshot:
    ticker = symbol(fields["symbol"], row)
    quantity = number(fields["quantity"], "quantity", row)
    if ticker is None or quantity is None:
        raise validation("持仓缺少证券代码或数量。", row)
    if "option" in label(fields.get("security_type", "")):
        raise validation("首版不支持期权持仓。", row)
    values = {
        field: number(fields.get(field, ""), field, row)
        for field in ("market_price", "market_value", "cost_basis", "unrealized_pnl")
    }
    if values["market_price"] == 0:
        values["market_price"] = None
    values["portfolio_weight"] = percent(
        fields.get("portfolio_weight", ""), "portfolio_weight", row
    )
    values["unrealized_pnl_percent"] = percent(
        fields.get("unrealized_pnl_percent", ""), "unrealized_pnl_percent", row
    )
    return PortfolioSnapshot(
        snapshot_id=record_id(
            "POS", account.account_id, observed_at, ticker, quantity, values
        ),
        account_id=account.account_id,
        account_role=account.role,
        broker=account.broker,
        snapshot_date=snapshot_date(observed_at),
        observed_at=observed_at,
        source=TransactionSource.CSV,
        symbol=ticker,
        quantity=quantity,
        **values,
    )
