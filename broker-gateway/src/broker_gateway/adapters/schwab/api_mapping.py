import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from shared.enums import (
    AccountRole,
    Broker,
    ErrorType,
    OrderDraftStatus,
    TransactionSource,
    TransactionType,
)
from shared.models import BrokerTransaction, PortfolioCashSnapshot, PortfolioSnapshot
from shared.models._types import Money, NonBlank, ShareAmount, SharedModel, UtcDatetime

from ...csv_import.normalizer import digest, record_id, snapshot_date
from .read_only import SchwabReadError, require_list, utc_time

_SECURITIES = {"EQUITY", "ETF", "MUTUAL_FUND"}
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-/]{0,19}\Z")
_MONEY_SCALE = Decimal("0.000001")
_EASTERN = ZoneInfo("America/New_York")


class SchwabAccount(SharedModel):
    account_id: NonBlank
    role: AccountRole
    broker_account_type: NonBlank | None = None
    observed_at: UtcDatetime
    liquidation_value: Money | None = None


class SchwabOrderStatus(SharedModel):
    account_id: NonBlank
    broker_order_id: NonBlank
    broker_status: NonBlank
    status: OrderDraftStatus
    entered_at: UtcDatetime | None = None
    quantity: ShareAmount | None = None
    filled_quantity: ShareAmount | None = None


def _invalid(message: str) -> SchwabReadError:
    return SchwabReadError(ErrorType.VALIDATION_ERROR, message)


def _dict(value: object) -> dict:
    if not isinstance(value, dict):
        raise _invalid("Schwab 响应的账户或证券字段不是对象。")
    return value


def _amount(data: dict, field: str) -> Decimal | None:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid(f"Schwab 数值字段 {field} 无效。")
    result = Decimal(value)
    if not result.is_finite():
        raise _invalid(f"Schwab 数值字段 {field} 无效。")
    return result


def _ticker(instrument: dict) -> str:
    label = instrument.get("symbol")
    if not isinstance(label, str) or not _TICKER.fullmatch(label):
        raise _invalid("Schwab 证券代码无效。")
    return label


def _identifier(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and 0 < len(value) <= 32
    ):
        return value
    raise _invalid("Schwab 记录缺少可验证的数字 ID。")


def account_snapshot(
    raw: dict, account_id: str, role: AccountRole, observed_at: datetime
) -> tuple[
    SchwabAccount, tuple[PortfolioSnapshot, ...], PortfolioCashSnapshot | None, int
]:
    day = snapshot_date(observed_at)
    balances = _dict(raw.get("currentBalances", {}))
    cash_values = {
        "cash_balance": _amount(balances, "cashBalance"),
        "available_to_trade": _amount(balances, "cashAvailableForTrading"),
    }
    account = SchwabAccount(
        account_id=account_id,
        role=role,
        broker_account_type=raw.get("type"),
        observed_at=observed_at,
        liquidation_value=_amount(balances, "liquidationValue"),
    )
    cash = None
    if any(value is not None for value in cash_values.values()):
        cash = PortfolioCashSnapshot(
            snapshot_id=record_id("CASH-API", account_id, observed_at, cash_values),
            account_id=account_id,
            observed_at=observed_at,
            snapshot_date=day,
            source=TransactionSource.API,
            **cash_values,
        )
    if "positions" not in raw:
        raise SchwabReadError(
            ErrorType.DATA_MISSING, "Schwab 未返回持仓字段，不能将其解释为空仓。"
        )
    positions = {}
    skipped = 0
    for row in require_list(raw["positions"]):
        instrument = _dict(row.get("instrument"))
        if instrument.get("assetType") not in _SECURITIES:
            skipped += 1
            continue
        ticker = _ticker(instrument)
        if ticker in positions:
            raise _invalid("Schwab 持仓在同一账户内重复出现同一标的。")
        long = _amount(row, "longQuantity")
        short = _amount(row, "shortQuantity")
        if any(value is not None and value < 0 for value in (long, short)):
            raise _invalid("Schwab 多头或空头持仓数量无效。")
        quantity = long - short if long is not None and short is not None else None
        average = _amount(row, "averagePrice")
        pnl = _amount(row, "longOpenProfitLoss") if long and short == 0 else None
        mark = _amount(row, "marketPrice")
        values = {
            "quantity": quantity,
            "market_value": _amount(row, "marketValue"),
            "market_price": mark if mark != 0 else None,
            "cost_basis": (
                (average * long).quantize(_MONEY_SCALE)
                if average is not None and long and short == 0
                else None
            ),
            "unrealized_pnl": pnl,
        }
        positions[ticker] = PortfolioSnapshot(
            snapshot_id=record_id("POS-API", account_id, observed_at, ticker, values),
            account_id=account_id,
            broker=Broker.SCHWAB,
            account_role=role,
            snapshot_date=day,
            observed_at=observed_at,
            symbol=ticker,
            source=TransactionSource.API,
            **values,
        )
    return account, tuple(positions.values()), cash, skipped


def _date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                pass
    raise _invalid("Schwab 返回了无效的交易或交割日期。")


def _instant(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return utc_time(datetime.fromisoformat(value))
        except ValueError:
            pass
    raise _invalid("Schwab 返回了无效或缺少时区的时间。")


def _fee(item: dict) -> Decimal:
    amount, cost = _amount(item, "amount"), _amount(item, "cost")
    if amount is None and cost is None:
        raise _invalid("Schwab 费用项目没有显式金额。")
    if amount and cost and abs(amount) != abs(cost):
        raise _invalid("Schwab 费用项目的金额字段不一致。")
    return abs(cost or amount or Decimal(0))


def trade_record(
    row: dict, account_id: str, start: datetime, end: datetime
) -> BrokerTransaction:
    if row.get("type") != "TRADE":
        raise _invalid("Schwab 响应包含超出 TRADE 请求范围的流水。")
    execution_id = _identifier(row.get("activityId"))
    when = _instant(row.get("time"))
    day = _date(row.get("tradeDate"))
    if day is None and when is not None:
        day = when.astimezone(_EASTERN).date()
    if day is None or (when is not None and not start <= when <= end):
        raise _invalid("Schwab 交易缺少交易日期或成交时间不在请求区间。")
    if (
        when is None
        and not start.astimezone(_EASTERN).date()
        <= day
        <= end.astimezone(_EASTERN).date()
    ):
        raise _invalid("Schwab 交易日期不在请求区间。")
    instruments, fees = [], []
    for item in require_list(row.get("transferItems")):
        security = _dict(item.get("instrument"))
        if security.get("assetType") == "CURRENCY":
            if security.get("symbol") not in ("USD", "CURRENCY_USD"):
                raise _invalid("首版只支持美元交易。")
            if item.get("feeType"):
                fees.append(_fee(item))
        else:
            instruments.append((item, security))
    if len(instruments) != 1 or instruments[0][1].get("assetType") not in _SECURITIES:
        raise _invalid("首版只支持单一股票、ETF 或基金证券腿的成交。")
    item, security = instruments[0]
    amount, price = _amount(item, "amount"), _amount(item, "price")
    if not amount or price is None or price <= 0:
        raise _invalid("Schwab 成交缺少有效的股数或成交价。")
    net = _amount(row, "netAmount")
    if net and (net > 0) == (amount > 0):
        raise _invalid("Schwab 成交净额方向与股数不一致。")
    gross = _amount(item, "cost")
    key = f"broker-id:{digest(execution_id)}"
    return BrokerTransaction(
        transaction_id=record_id("TXN", account_id, Broker.SCHWAB, key),
        account_id=account_id,
        broker=Broker.SCHWAB,
        symbol=_ticker(security),
        trade_date=day,
        transaction_time=when,
        settlement_date=_date(row.get("settlementDate")),
        transaction_type=TransactionType.BUY if amount > 0 else TransactionType.SELL,
        quantity=abs(amount),
        price=price,
        gross_amount=(
            abs(gross)
            if gross is not None
            else (abs(amount) * price).quantize(_MONEY_SCALE)
        ),
        fee=sum(fees, Decimal(0)) if fees else None,
        net_amount=net,
        broker_transaction_id=execution_id,
        broker_order_id=(
            _identifier(row["orderId"]) if row.get("orderId") is not None else None
        ),
        deduplication_key=key,
        source=TransactionSource.API,
    )


_FINAL = {
    "CANCELED": OrderDraftStatus.CANCELED,
    "EXPIRED": OrderDraftStatus.EXPIRED,
    "REJECTED": OrderDraftStatus.REJECTED,
    "FILLED": OrderDraftStatus.FILLED,
}
_WORKING = {
    "WORKING",
    "QUEUED",
    "NEW",
    "ACCEPTED",
    "PENDING_ACTIVATION",
    "AWAITING_PARENT_ORDER",
    "AWAITING_CONDITION",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "PENDING_ACKNOWLEDGEMENT",
}


def order_status(row: dict, account_id: str) -> SchwabOrderStatus:
    label = row.get("status")
    if not isinstance(label, str) or not re.fullmatch(r"[A-Z_]{1,64}", label):
        raise _invalid("Schwab 订单状态字段无效。")
    quantity, filled = _amount(row, "quantity"), _amount(row, "filledQuantity")
    if any(value is not None and value < 0 for value in (quantity, filled)):
        raise _invalid("Schwab 订单数量为负。")
    status = _FINAL.get(label, OrderDraftStatus.UNKNOWN)
    if label in _WORKING:
        if filled is not None and quantity is not None and 0 < filled < quantity:
            status = OrderDraftStatus.PARTIALLY_FILLED
        else:
            status = OrderDraftStatus.SUBMITTED
    return SchwabOrderStatus(
        account_id=account_id,
        broker_order_id=_identifier(row.get("orderId")),
        broker_status=label,
        status=status,
        entered_at=_instant(row.get("enteredTime")),
        quantity=quantity,
        filled_quantity=filled,
    )
