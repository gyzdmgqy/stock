from datetime import date

import pandas as pd
import pytest

from analysis_engine.services.signal_service import AnalysisError, DailySignalService
from market_data.repositories.daily_price_repository import DailyPriceRepository
from market_data.repositories.intraday_price_repository import IntradayPriceRepository
from shared.db import connect_database, initialize_database
from shared.enums import Action, ErrorType, MarketRegime, PriceLocation
from shared.models import DailyPrice, DailySignal, IntradayPrice


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "analysis.duckdb"
    initialize_database(path)
    with connect_database(path) as connection:
        yield connection


@pytest.fixture
def candles():
    dates = pd.bdate_range(end="2026-06-05", periods=201).date
    bars = [
        DailyPrice(
            symbol="VOO",
            trade_date=day,
            open=100,
            high=101,
            low=98,
            close=99 if i == 194 else 100,
            volume=125 if i == 194 else 100,
            adjusted_close=80,
        )
        for i, day in enumerate(dates)
    ]
    bars[-1] = DailyPrice(
        symbol="VOO",
        trade_date=dates[-1],
        open=100,
        high=103,
        low=95,
        close=102,
        volume=150,
        adjusted_close=81,
    )
    return bars


def test_daily_signal_persists_indicators_and_rules_without_lookahead(db, candles):
    repo = DailyPriceRepository(db)
    repo.upsert_daily_prices(candles)
    service = DailySignalService(db)
    last = candles[-1].trade_date
    signal = service.generate_daily_signal(" voo ", last)
    assert isinstance(signal, DailySignal)
    assert signal.symbol == "VOO"
    assert signal.trade_date == last
    assert signal.market_regime is MarketRegime.TREND_UP
    assert signal.price_location is PriceLocation.ABOVE_MA200
    assert signal.false_breakdown_score == 100
    assert signal.volume_confirmation_score == 100
    assert signal.action_hint is Action.WATCH
    assert signal.reason
    assert db.execute(
        "SELECT ma200, atr14 IS NOT NULL, rsi14 IS NOT NULL, volume_avg5, volume_ratio_5 "
        "FROM daily_indicator WHERE symbol = 'VOO' AND trade_date = ?",
        [last],
    ).fetchone() == (100.005, True, True, 110.0, 1.5)
    assert db.execute(
        "SELECT false_breakdown_score, volume_confirmation_score "
        "FROM daily_signal WHERE signal_id = ?",
        [signal.signal_id],
    ).fetchone() == (100.0, 100.0)
    evidence = dict(
        db.execute(
            "SELECT rule_name, rule_value FROM signal_detail WHERE signal_id = ?",
            [signal.signal_id],
        ).fetchall()
    )
    assert evidence["low_below_ma200"] == "true"
    assert evidence["volume_above_previous_down_day"] == "true"

    repo.upsert_daily_prices(
        [candles[-1].model_copy(update={"trade_date": date(2026, 6, 8)})]
    )
    assert service.generate_daily_signal("VOO", last).signal_id == signal.signal_id


def test_idempotent_run_and_price_correction_keep_prior_signal(db, candles):
    repo = DailyPriceRepository(db)
    repo.upsert_daily_prices(candles)
    service = DailySignalService(db)
    last = candles[-1].trade_date
    signal = service.generate_daily_signal("VOO", last)
    same = service.generate_daily_signal("VOO", last)
    assert same == signal
    assert db.execute("SELECT count(*) FROM daily_signal").fetchone() == (1,)

    repo.upsert_daily_prices([candles[-1].model_copy(update={"volume": 250})])
    changed = service.generate_daily_signal("VOO", last)
    assert changed.signal_id != signal.signal_id
    assert changed.false_breakdown_score < 70
    assert db.execute("SELECT count(*) FROM daily_signal").fetchone() == (2,)
    assert db.execute("SELECT count(*) FROM daily_indicator").fetchone() == (1,)
    assert db.execute(
        "SELECT false_breakdown_score FROM daily_signal WHERE signal_id = ?",
        [signal.signal_id],
    ).fetchone() == (100.0,)


def test_short_history_keeps_unknown_metrics_and_never_substitutes_old_date(
    db, candles
):
    DailyPriceRepository(db).upsert_daily_prices(candles[-4:])
    service = DailySignalService(db)
    signal = service.generate_daily_signal("VOO", candles[-1].trade_date)
    assert signal.action_hint is Action.WATCH
    assert signal.market_regime is None
    assert signal.price_location is None
    assert signal.false_breakdown_score is None
    assert signal.volume_confirmation_score is None

    with pytest.raises(AnalysisError) as error:
        service.generate_daily_signal("VOO", date(2026, 6, 8))
    assert error.value.error_type is ErrorType.DATA_MISSING
    assert db.execute("SELECT count(*) FROM daily_signal").fetchone() == (1,)


def test_same_session_hourly_low_can_confirm_a_new_signal_version(db, candles):
    candle = DailyPrice.model_validate(
        {**candles[-1].model_dump(), "open": 101, "low": 100, "high": 102}
    )
    DailyPriceRepository(db).upsert_daily_prices([*candles[:-1], candle])
    service = DailySignalService(db)
    old = service.generate_daily_signal("VOO", candle.trade_date)
    assert old.false_breakdown_score < 70
    IntradayPriceRepository(db).upsert_intraday_prices(
        [
            IntradayPrice(
                symbol="VOO",
                trade_date=candle.trade_date,
                bar_start="2026-06-05T14:30:00Z",
                low=99,
            )
        ]
    )
    new = service.generate_daily_signal("VOO", candle.trade_date)
    assert new.false_breakdown_score == 100
    assert new.signal_id != old.signal_id


def test_failed_signal_write_rolls_back_the_indicator(db, candles):
    DailyPriceRepository(db).upsert_daily_prices(candles)
    db.execute("DROP TABLE signal_detail")
    with pytest.raises(AnalysisError):
        DailySignalService(db).generate_daily_signal("VOO", candles[-1].trade_date)
    assert db.execute("SELECT count(*) FROM daily_indicator").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM daily_signal").fetchone() == (0,)
