from duckdb import DuckDBPyConnection

from shared.enums import Broker, TransactionSource
from shared.models import BrokerTransaction

_ECONOMICS = (
    "trade_date",
    "symbol",
    "transaction_type",
    "quantity",
    "price",
    "gross_amount",
    "fee",
    "net_amount",
)
_FILL = ("quantity", "price")


class TransactionOverlapError(ValueError):
    pass


def require_compatible_economics(candidate: BrokerTransaction, stored: dict) -> None:
    for key in _ECONOMICS:
        left, right = getattr(candidate, key), stored[key]
        if left is not None and right is not None and left != right:
            raise TransactionOverlapError(
                "同一券商成交 ID 的交易事实冲突，需要人工对账。"
            )


def matched_other_source(
    db: DuckDBPyConnection,
    candidate: BrokerTransaction,
    *,
    incoming_api_ids: frozenset[str] = frozenset(),
) -> bool:
    if candidate.broker is not Broker.SCHWAB or candidate.source not in (
        TransactionSource.API,
        TransactionSource.CSV,
    ):
        return False
    other = (
        TransactionSource.CSV
        if candidate.source is TransactionSource.API
        else TransactionSource.API
    )
    columns = ("broker_transaction_id", *_ECONOMICS)
    rows = db.execute(
        f"""
        SELECT {', '.join(columns)} FROM broker_transaction
        WHERE broker = 'SCHWAB' AND account_id = ? AND source = ? AND (
            broker_transaction_id = ?
            OR (trade_date = ? AND transaction_type = ? AND symbol IS NOT DISTINCT FROM ?)
        )
        """,
        [
            candidate.account_id,
            other.value,
            candidate.broker_transaction_id,
            candidate.trade_date,
            candidate.transaction_type.value,
            candidate.symbol,
        ],
    ).fetchall()
    records = [dict(zip(columns, row, strict=True)) for row in rows]
    matching = [
        row
        for row in records
        if candidate.broker_transaction_id is not None
        and row["broker_transaction_id"] == candidate.broker_transaction_id
    ]
    if matching:
        if len(matching) != 1:
            raise TransactionOverlapError(
                "同一券商成交 ID 已对应多笔记录，需要人工对账。"
            )
        require_compatible_economics(candidate, matching[0])
        return True
    if any(
        row["broker_transaction_id"] not in incoming_api_ids
        and row["trade_date"] == candidate.trade_date
        and row["transaction_type"] == candidate.transaction_type
        and row["symbol"] == candidate.symbol
        and all(
            row[field] is None
            or getattr(candidate, field) is None
            or row[field] == getattr(candidate, field)
            for field in _FILL
        )
        for row in records
    ):
        raise TransactionOverlapError(
            "API 和 CSV 的成交可能重叠，但没有相同的券商成交 ID；请改用不重叠的区间或先对账。"
        )
    return False
