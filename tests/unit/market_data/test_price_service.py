from datetime import UTC, date, datetime, timedelta

import pytest

from market_data.errors import MarketDataError
from market_data.repositories.daily_price_repository import DailyPriceRepository
from market_data.repositories.intraday_price_repository import IntradayPriceRepository
from market_data.services.daily_price_service import DailyPriceService
from shared.db import connect_database, initialize_database
from shared.enums import ErrorType
from shared.models import DailyPrice, IntradayPrice

FIRST = date(2026, 6, 4)
SECOND = date(2026, 6, 5)


class StubProvider:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_daily_prices(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return self.bars


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "market.duckdb"
    initialize_database(path)
    return path


def make_bar(day, close, *, symbol="VOO"):
    return DailyPrice(
        symbol=symbol,
        trade_date=day,
        open=100.0,
        high=120.0,
        low=95.0,
        close=close,
        adjusted_close=close - 1,
        volume=200,
        source="stub",
    )


def test_service_uses_provider_contract_and_prices_can_be_queried_after_reopen(
    database,
):
    provider = StubProvider([make_bar(SECOND, 111), make_bar(FIRST, 110)])
    with connect_database(database) as db:
        repository = DailyPriceRepository(db)
        DailyPriceService(provider, repository).download_daily_prices(
            " voo ", FIRST, SECOND
        )

    assert provider.calls == [("VOO", FIRST, SECOND)]
    with connect_database(database, read_only=True) as db:
        repository = DailyPriceRepository(db)
        bars = repository.get_daily_prices("VOO", FIRST, SECOND)
        assert [(bar.trade_date, bar.close) for bar in bars] == [
            (FIRST, 110),
            (SECOND, 111),
        ]
        assert repository.get_daily_prices("VOO", SECOND, SECOND) == [bars[-1]]
        assert repository.get_latest_daily_price("voo") == bars[-1]
        assert repository.get_latest_daily_price("QQQ") is None
        assert repository.get_daily_prices("QQQ", FIRST, SECOND) == []


def test_daily_upsert_updates_row_without_duplicating_or_resetting_created_at(database):
    with connect_database(database) as db:
        repository = DailyPriceRepository(db)
        repository.upsert_daily_prices([make_bar(FIRST, 110)])
        original = repository.get_latest_daily_price("VOO")
        repository.upsert_daily_prices([make_bar(FIRST, 115), make_bar(FIRST, 118)])
        rows = repository.get_daily_prices("VOO", FIRST, SECOND)
        assert len(rows) == 1
        assert rows[0].close == 118
        assert rows[0].created_at == original.created_at


def test_empty_provider_data_returns_structured_missing_error(database):
    with connect_database(database) as db:
        service = DailyPriceService(StubProvider([]), DailyPriceRepository(db))
        with pytest.raises(MarketDataError) as error:
            service.download_daily_prices("MISSING", FIRST, SECOND)
        assert error.value.error_type is ErrorType.DATA_MISSING
        assert db.execute("SELECT count(*) FROM daily_price").fetchone() == (0,)


def test_invalid_request_does_not_call_provider(database):
    provider = StubProvider([])
    with connect_database(database) as db:
        service = DailyPriceService(provider, DailyPriceRepository(db))
        with pytest.raises(MarketDataError) as error:
            service.download_daily_prices("VOO", SECOND, FIRST)
        assert error.value.error_type is ErrorType.VALIDATION_ERROR
    assert not provider.calls


@pytest.mark.parametrize(
    "bar",
    [
        make_bar(SECOND, 111, symbol="QQQ"),
        make_bar(SECOND + timedelta(days=1), 111),
        DailyPrice(symbol="VOO", trade_date=SECOND),
    ],
)
def test_invalid_provider_batch_does_not_write_a_partial_result(database, bar):
    with connect_database(database) as db:
        repository = DailyPriceRepository(db)
        service = DailyPriceService(
            StubProvider([make_bar(FIRST, 110), bar]), repository
        )
        with pytest.raises(MarketDataError) as error:
            service.download_daily_prices("VOO", FIRST, SECOND)
        assert error.value.error_type is ErrorType.VALIDATION_ERROR
        assert repository.get_daily_prices("VOO", FIRST, SECOND) == []


def test_read_only_write_reports_structured_error(database):
    with connect_database(database, read_only=True) as db:
        service = DailyPriceService(
            StubProvider([make_bar(FIRST, 110)]), DailyPriceRepository(db)
        )
        with pytest.raises(MarketDataError) as error:
            service.download_daily_prices("VOO", FIRST, SECOND)
        assert error.value.error_type is ErrorType.UNKNOWN
        assert error.value.retryable is False


def test_hourly_repository_round_trips_by_utc_bar_key(database):
    earlier = IntradayPrice(
        symbol="VOO",
        trade_date=SECOND,
        bar_start="2026-06-05T09:30:00-04:00",
        close=110.0,
        volume=30,
        source="fixture",
    )
    later = IntradayPrice(
        symbol="VOO",
        trade_date=SECOND,
        bar_start="2026-06-05T14:30:00Z",
        close=112.0,
        volume=40,
        source="fixture",
    )
    with connect_database(database) as db:
        repository = IntradayPriceRepository(db)
        repository.upsert_intraday_prices([later, earlier])
        repository.upsert_intraday_prices([earlier.model_copy(update={"close": 111.0})])
    with connect_database(database, read_only=True) as db:
        bars = IntradayPriceRepository(db).get_intraday_prices("VOO", SECOND)
        assert [(bar.interval, bar.close) for bar in bars] == [("1h", 111), ("1h", 112)]
        assert bars[0].bar_start == datetime(2026, 6, 5, 13, 30, tzinfo=UTC)
