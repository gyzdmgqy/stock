from datetime import date

import pandas as pd
import pytest
from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

from market_data.errors import MarketDataError
from market_data.providers import yfinance_provider
from market_data.providers.yfinance_provider import YFinanceProvider
from shared.enums import ErrorType
from shared.models import DailyPrice

START = date(2026, 6, 4)
END = date(2026, 6, 5)


@pytest.fixture
def history():
    return pd.DataFrame(
        {
            "Open": [110.0, 100.0],
            "High": [120.0, 110.0],
            "Low": [105.0, 95.0],
            "Close": [115.0, 105.0],
            "Adj Close": [111.0, 101.0],
            "Volume": [300, 200],
        },
        index=pd.DatetimeIndex(
            ["2026-06-05", "2026-06-04"], tz="Asia/Tokyo", name="Date"
        ),
    )


def stub_history(monkeypatch, history):
    calls = []

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            calls.append((self.symbol, kwargs))
            if isinstance(history, Exception):
                raise history
            return history

    monkeypatch.setattr(yfinance_provider.yf, "Ticker", Ticker)
    return calls


def test_normalizes_provider_bars_and_includes_end_date(monkeypatch, history):
    calls = stub_history(monkeypatch, history)

    bars = YFinanceProvider().fetch_daily_prices(" voo ", START, END)

    symbol, request = calls[0]
    assert symbol == "VOO"
    assert request["start"] == START.isoformat()
    assert request["end"] == "2026-06-06"
    assert request["auto_adjust"] is False
    assert request["interval"] == "1d"
    assert [bar.trade_date for bar in bars] == [START, END]
    assert bars[-1] == DailyPrice(
        symbol="VOO",
        trade_date=END,
        open=110.0,
        high=120.0,
        low=105.0,
        close=115.0,
        adjusted_close=111.0,
        volume=300,
        source="yfinance",
    )


def test_missing_adjusted_close_remains_null(monkeypatch, history):
    stub_history(monkeypatch, history.drop(columns="Adj Close"))
    assert all(
        bar.adjusted_close is None
        for bar in YFinanceProvider().fetch_daily_prices("VOO", START, END)
    )


def test_duplicate_dates_keep_each_source_row_aligned(monkeypatch, history):
    corrected = history.iloc[[0]].assign(Close=116.0, **{"Adj Close": 112.0})
    stub_history(monkeypatch, pd.concat([history, corrected]))

    bars = YFinanceProvider().fetch_daily_prices("VOO", START, END)
    assert [
        (bar.close, bar.adjusted_close) for bar in bars if bar.trade_date == END
    ] == [(115.0, 111.0), (116.0, 112.0)]


@pytest.mark.parametrize(
    ("response", "expected", "retryable"),
    [
        (pd.DataFrame(), ErrorType.DATA_MISSING, False),
        (YFPricesMissingError("MISSING", "no data"), ErrorType.DATA_MISSING, False),
        (YFRateLimitError(), ErrorType.UNKNOWN, True),
    ],
)
def test_provider_failure_is_structured(monkeypatch, response, expected, retryable):
    stub_history(monkeypatch, response)
    with pytest.raises(MarketDataError) as error:
        YFinanceProvider().fetch_daily_prices("MISSING", START, END)
    envelope = error.value.to_message(target="analysis-engine")
    assert envelope["message_type"] == "ERROR"
    assert envelope["source"] == "market-data-service"
    assert envelope["target"] == "analysis-engine"
    assert envelope["symbol"] == "MISSING"
    assert envelope["payload"]["error_type"] == expected.value
    assert envelope["payload"]["retryable"] is retryable
    assert envelope["payload"]["error_message"]
    assert envelope["payload"]["suggested_action"]


@pytest.mark.parametrize("invalid", [None, 2.3, -1, float("inf")])
def test_invalid_provider_volume_fails_with_trading_date(monkeypatch, history, invalid):
    history["Volume"] = [invalid, 100]
    stub_history(monkeypatch, history)

    with pytest.raises(MarketDataError) as error:
        YFinanceProvider().fetch_daily_prices("VOO", START, END)
    assert error.value.error_type is ErrorType.VALIDATION_ERROR
    assert error.value.to_message()["trade_date"] == END.isoformat()


def test_malformed_provider_columns_are_not_treated_as_missing_ticker(
    monkeypatch, history
):
    stub_history(monkeypatch, history.drop(columns="Close"))
    with pytest.raises(MarketDataError) as error:
        YFinanceProvider().fetch_daily_prices("VOO", START, END)
    assert error.value.error_type is ErrorType.VALIDATION_ERROR
