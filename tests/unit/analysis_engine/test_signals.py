from datetime import date

import pytest

from analysis_engine.signals.false_breakdown import (
    lower_shadow_fraction,
    score_false_breakdown,
)
from analysis_engine.signals.gap_analysis import analyze_gap
from analysis_engine.signals.market_regime import (
    classify_market,
    classify_price_location,
)
from analysis_engine.signals.volume_confirmation import score_volume_confirmation
from shared.enums import GapDirection, GapType, MarketRegime, PriceLocation, TrendState
from shared.models import DailyPrice


@pytest.fixture
def recovery_bar():
    return DailyPrice(
        symbol="VOO",
        trade_date=date(2026, 6, 5),
        open=100,
        high=103,
        low=95,
        close=102,
        volume=150,
    )


@pytest.mark.parametrize(
    ("close", "expected"),
    [
        (98.99, PriceLocation.BELOW_MA200),
        (99.0, PriceLocation.NEAR_MA200),
        (100.0, PriceLocation.NEAR_MA200),
        (101.0, PriceLocation.NEAR_MA200),
        (101.01, PriceLocation.ABOVE_MA200),
    ],
)
def test_price_location_has_inclusive_near_boundaries(close, expected):
    assert classify_price_location(close, 100) is expected


def test_regime_uses_ma_alignment_with_priority_for_down_day_panic():
    assert classify_market(115, 110, 105, 100, previous_close=114, volume_ratio=1) == (
        MarketRegime.TREND_UP,
        TrendState.STRONG_UP,
    )
    assert classify_market(97, 98, 99, 100, previous_close=98, volume_ratio=1) == (
        MarketRegime.TREND_DOWN,
        TrendState.STRONG_DOWN,
    )
    assert classify_market(110, 101, 103, 100, previous_close=109, volume_ratio=1) == (
        MarketRegime.RANGE,
        TrendState.WEAK_UP,
    )
    assert classify_market(115, 110, 105, 100, previous_close=116, volume_ratio=2) == (
        MarketRegime.HIGH_RISK,
        TrendState.STRONG_UP,
    )
    assert classify_market(103, 102, 100, None, previous_close=102, volume_ratio=1) == (
        None,
        None,
    )


def test_long_lower_shadow_and_complete_false_breakdown(recovery_bar):
    assert lower_shadow_fraction(recovery_bar) == pytest.approx(5 / 8)
    result = score_false_breakdown(recovery_bar, ma200=100, prior_volume_avg5=100)
    assert result.score == 100
    assert sum(detail.score for detail in result.details) == 100
    assert any(
        detail.rule_name == "low_below_ma200" and detail.rule_value == "true"
        for detail in result.details
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"low": 100},
        {"open": 98, "close": 100},
        {"open": 100, "low": 99},
        {"volume": 200},
    ],
)
def test_every_breakdown_check_must_pass_for_a_confirmed_score(recovery_bar, changes):
    bar = DailyPrice.model_validate({**recovery_bar.model_dump(), **changes})
    assert score_false_breakdown(bar, ma200=100, prior_volume_avg5=100).score < 70


def test_hourly_low_can_supply_missing_breach(recovery_bar):
    bar = DailyPrice.model_validate(
        {**recovery_bar.model_dump(), "open": 101, "low": 100, "high": 102}
    )
    assert score_false_breakdown(bar, ma200=100, prior_volume_avg5=100).score < 70
    assert (
        score_false_breakdown(
            bar, ma200=100, prior_volume_avg5=100, intraday_low=99
        ).score
        == 100
    )


def test_breakdown_warmup_and_zero_range(recovery_bar):
    result = score_false_breakdown(recovery_bar, ma200=None, prior_volume_avg5=100)
    assert result.score is None
    assert any(detail.rule_value == "null" for detail in result.details)
    flat = DailyPrice.model_validate(
        {
            **recovery_bar.model_dump(),
            **dict.fromkeys(("open", "high", "low", "close"), 100),
        }
    )
    assert lower_shadow_fraction(flat) == 0
    assert score_false_breakdown(flat, ma200=100, prior_volume_avg5=0).score is None


def test_volume_confirmation_uses_previous_down_day_and_prior_average(recovery_bar):
    result = score_volume_confirmation(
        recovery_bar,
        previous_close=100,
        prior_volume_avg5=100,
        previous_down_volume=125,
    )
    assert result.score == 100
    result = score_volume_confirmation(
        recovery_bar,
        previous_close=100,
        prior_volume_avg5=100,
        previous_down_volume=150,
    )
    assert result.score == pytest.approx(200 / 3)
    assert (
        score_volume_confirmation(
            recovery_bar,
            previous_close=102,
            prior_volume_avg5=100,
            previous_down_volume=125,
        ).score
        == 0
    )
    assert (
        score_volume_confirmation(
            recovery_bar,
            previous_close=100,
            prior_volume_avg5=100,
            previous_down_volume=None,
        ).score
        is None
    )


def test_gap_labels_need_evidence_and_gap_is_in_percentage_points(recovery_bar):
    assert analyze_gap(recovery_bar, previous_close=None, volume_ratio=None) == (
        None,
        None,
        None,
    )
    assert analyze_gap(recovery_bar, previous_close=100.2, volume_ratio=1)[:2] == (
        GapType.NONE,
        GapDirection.NONE,
    )
    kind, direction, percent = analyze_gap(
        recovery_bar, previous_close=101, volume_ratio=1
    )
    assert (kind, direction) == (GapType.SHAKEOUT, GapDirection.DOWN)
    assert percent == pytest.approx(-100 / 101)
    assert analyze_gap(recovery_bar, previous_close=105, volume_ratio=2)[:2] == (
        GapType.PANIC,
        GapDirection.DOWN,
    )
    assert analyze_gap(recovery_bar, previous_close=98, volume_ratio=1)[:2] == (
        None,
        GapDirection.UP,
    )
