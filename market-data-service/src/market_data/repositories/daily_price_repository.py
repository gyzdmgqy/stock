from collections.abc import Iterable
from datetime import date

from duckdb import DuckDBPyConnection

from shared.models import DailyPrice

from .._requests import normalize_symbol, validate_dates
from ._prices import read_bars, upsert_bars

_COLUMNS = ", ".join(DailyPrice.model_fields)


class DailyPriceRepository:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._db = db

    def upsert_daily_prices(self, bars: Iterable[DailyPrice]) -> list[DailyPrice]:
        return upsert_bars(
            self._db, "daily_price", DailyPrice, ("symbol", "trade_date"), bars
        )

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[DailyPrice]:
        symbol = normalize_symbol(symbol)
        validate_dates(symbol, start, end)
        return read_bars(
            self._db,
            DailyPrice,
            f"SELECT {_COLUMNS} FROM daily_price "
            "WHERE symbol = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [symbol, start, end],
        )

    def get_latest_daily_price(self, symbol: str) -> DailyPrice | None:
        bars = read_bars(
            self._db,
            DailyPrice,
            f"SELECT {_COLUMNS} FROM daily_price "
            "WHERE symbol = ? ORDER BY trade_date DESC LIMIT 1",
            [normalize_symbol(symbol)],
        )
        return bars[0] if bars else None
