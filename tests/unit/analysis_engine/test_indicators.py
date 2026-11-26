import pandas as pd
import pytest

from analysis_engine.indicators.moving_average import moving_averages
from analysis_engine.indicators.volatility import atr, rsi
from analysis_engine.indicators.volume import volume_indicators


def test_moving_averages_use_full_windows_and_current_close():
    close = pd.Series(range(1, 202), dtype=float)
    values = moving_averages(close)
    for window in (5, 10, 20, 30, 50, 100, 200):
        ma = values[f"ma{window}"]
        assert pd.isna(ma.iloc[window - 2])
        assert ma.iloc[window - 1] == (1 + window) / 2
        assert ma.iloc[-1] == 201 - (window - 1) / 2


def test_atr_uses_previous_close_and_wilder_seed():
    high = pd.Series([102.0] * 14 + [111.0])
    low = pd.Series([98.0] * 14 + [109.0])
    close = pd.Series([100.0] * 14 + [110.0])
    result = atr(high, low, close)
    assert result.iloc[:13].isna().all()
    assert result.iloc[13] == 4.0
    assert result.iloc[14] == pytest.approx((13 * 4 + 11) / 14)


@pytest.mark.parametrize(("step", "expected"), [(1.0, 100.0), (-1.0, 0.0), (0.0, 50.0)])
def test_rsi_warms_up_for_fourteen_changes(step, expected):
    result = rsi(pd.Series([100.0 + step * day for day in range(16)]))
    assert result.iloc[:14].isna().all()
    assert result.iloc[14] == expected


def test_rsi_wilders_update_for_mixed_prices():
    close = pd.Series([100.0, 102.0, 101.0, 104.0, 102.0])
    result = rsi(close, period=3)
    assert result.iloc[3] == pytest.approx(100 * (5 / 3) / 2)
    assert result.iloc[4] == pytest.approx(100 * (10 / 9) / (10 / 9 + 8 / 9))


def test_volume_ratio_compares_current_volume_with_prior_sessions():
    volume = pd.Series([100.0] * 20 + [200.0])
    result = volume_indicators(volume)
    assert pd.isna(result["volume_avg5"].iloc[3])
    assert pd.isna(result["volume_ratio_5"].iloc[4])
    assert result["volume_avg5"].iloc[-1] == 120.0
    assert result["volume_avg20"].iloc[-1] == 105.0
    assert result["volume_ratio_5"].iloc[-1] == 2.0
    assert result["volume_ratio_20"].iloc[-1] == 2.0
    assert pd.isna(
        volume_indicators(pd.Series([0] * 5 + [1]))["volume_ratio_5"].iloc[-1]
    )
