from datetime import date, timedelta
from numbers import Real

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError, YFTickerMissingError

from shared.enums import ErrorType
from shared.models import DailyPrice

from .._requests import normalize_symbol, validate_dates
from ..errors import MarketDataError, missing_prices

_REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class YFinanceProvider:
    def fetch_daily_prices(
        self, symbol: str, start: date, end: date
    ) -> list[DailyPrice]:
        symbol = normalize_symbol(symbol)
        validate_dates(symbol, start, end)
        if end == date.max:
            raise self._invalid_history(symbol, "结束日期超出数据源支持的范围")

        try:
            frame = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                keepna=True,
                raise_errors=True,
            )
        except YFTickerMissingError as exc:
            raise missing_prices(symbol) from exc
        except YFRateLimitError as exc:
            raise MarketDataError(
                ErrorType.UNKNOWN,
                "Yahoo Finance 限制了行情请求频率",
                symbol=symbol,
                retryable=True,
                suggested_action="降低请求频率后重试。",
            ) from exc
        except Exception as exc:
            raise MarketDataError(
                ErrorType.UNKNOWN,
                "Yahoo Finance 行情请求失败",
                symbol=symbol,
                retryable=True,
                suggested_action="检查网络和行情数据源状态后重试。",
            ) from exc

        return self._normalize_history(symbol, frame, start, end)

    def _normalize_history(
        self, symbol: str, frame: pd.DataFrame, start: date, end: date
    ) -> list[DailyPrice]:
        if not isinstance(frame, pd.DataFrame):
            raise self._invalid_history(symbol, "行情数据源返回了未知的数据结构")
        if len(frame.index) == 0:
            raise missing_prices(symbol)
        if (
            not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.hasnans
            or not frame.columns.is_unique
            or any(column not in frame for column in _REQUIRED_COLUMNS)
        ):
            raise self._invalid_history(symbol, "行情响应缺少有效日期或 OHLCV 列")

        selected = frame.reindex(columns=[*_REQUIRED_COLUMNS, "Adj Close"])
        bars = []
        for index, open_, high, low, close, volume, adjusted in selected.itertuples(
            name=None
        ):
            trade_date = index.date()
            if not start <= trade_date <= end:
                continue
            try:
                if (
                    isinstance(volume, bool)
                    or not isinstance(volume, Real)
                    or not 0 <= volume < 2**63
                    or volume % 1 != 0
                ):
                    raise ValueError("成交量必须为非负整数")
                if any(value is None for value in (open_, high, low, close)):
                    raise ValueError("行情响应缺少 OHLC 价格")
                bars.append(
                    DailyPrice(
                        symbol=symbol,
                        trade_date=trade_date,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=int(volume),
                        adjusted_close=None if pd.isna(adjusted) else adjusted,
                        source="yfinance",
                    )
                )
            except (TypeError, ValueError) as exc:
                raise self._invalid_history(
                    symbol, "行情响应中的 OHLCV 数值无效", trade_date
                ) from exc

        if not bars:
            raise missing_prices(symbol)
        return sorted(bars, key=lambda bar: bar.trade_date)

    @staticmethod
    def _invalid_history(
        symbol: str, message: str, trade_date: date | None = None
    ) -> MarketDataError:
        return MarketDataError(
            ErrorType.VALIDATION_ERROR,
            message,
            symbol=symbol,
            trade_date=trade_date,
            suggested_action="检查日期边界和行情数据源返回的数据。",
        )
