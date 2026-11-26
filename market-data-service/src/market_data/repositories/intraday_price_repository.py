from collections.abc import Iterable
from datetime import date

from duckdb import DuckDBPyConnection

from shared.models import IntradayPrice

from .._requests import normalize_symbol, validate_dates
from ._prices import read_bars, upsert_bars

_COLUMNS = ", ".join(f'"{column}"' for column in IntradayPrice.model_fields)


class IntradayPriceRepository:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._db = db

    def upsert_intraday_prices(
        self, bars: Iterable[IntradayPrice]
    ) -> list[IntradayPrice]:
        return upsert_bars(
            self._db,
            "intraday_price",
            IntradayPrice,
            ("symbol", "interval", "bar_start"),
            bars,
        )

    def get_intraday_prices(self, symbol: str, trade_date: date) -> list[IntradayPrice]:
        symbol = normalize_symbol(symbol)
        validate_dates(symbol, trade_date, trade_date)
        return read_bars(
            self._db,
            IntradayPrice,
            f"SELECT {_COLUMNS} FROM intraday_price "
            "WHERE symbol = ? AND trade_date = ? AND \"interval\" = '1h' ORDER BY bar_start",
            [symbol, trade_date],
        )
