from datetime import date, datetime, time
from decimal import ROUND_UP, Decimal

from duckdb import DuckDBPyConnection

from .hourly_gate import APP_TIMEZONE


def completed_sessions(
    sessions: tuple[date, ...], as_of: datetime, session_close: datetime | None = None
) -> tuple[date, ...]:
    local = as_of.astimezone(APP_TIMEZONE)
    if (
        session_close is not None
        and session_close.astimezone(APP_TIMEZONE).date() != local.date()
    ):
        raise ValueError("收盘时刻与芝加哥业务日期不一致。")
    closed = (
        as_of >= session_close
        if session_close is not None
        else local.time() >= time(15)
    )
    return tuple(
        day
        for day in sessions
        if day < local.date() or (day == local.date() and closed)
    )


def two_closes_below_ma200(
    db: DuckDBPyConnection, symbol: str, days: tuple[date, ...]
) -> bool:
    if len(days) != 2:
        return False
    rows = db.execute(
        """
        SELECT p.close, i.ma200 FROM daily_price AS p
        JOIN daily_indicator AS i USING (symbol, trade_date)
        WHERE p.symbol = ? AND p.trade_date IN (?, ?)
        """,
        [symbol, *days],
    ).fetchall()
    return len(rows) == 2 and all(
        close is not None and ma200 is not None and 0 < close < ma200
        for close, ma200 in rows
    )


def required_reduction_quantity(
    quantity: Decimal,
    position_value: Decimal | None,
    account_equity: Decimal | None,
    max_weight: Decimal,
) -> Decimal | None:
    if quantity <= 0 or account_equity is None or account_equity <= 0:
        return None
    cap = account_equity * max_weight
    if position_value is None or position_value <= cap:
        return None
    excess = (position_value - cap) * quantity / position_value
    return min(quantity, excess.quantize(Decimal("0.00000001"), rounding=ROUND_UP))
