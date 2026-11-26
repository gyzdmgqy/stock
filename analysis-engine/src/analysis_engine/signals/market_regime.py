from shared.enums import MarketRegime, PriceLocation, TrendState

from .rules import DEFAULT_RULES, SignalRules


def classify_price_location(
    close: float, ma200: float | None, *, rules: SignalRules = DEFAULT_RULES
) -> PriceLocation | None:
    if ma200 is None:
        return None
    lower = ma200 * (1 - rules.near_ma200_fraction)
    upper = ma200 * (1 + rules.near_ma200_fraction)
    if lower <= close <= upper:
        return PriceLocation.NEAR_MA200
    return PriceLocation.ABOVE_MA200 if close > upper else PriceLocation.BELOW_MA200


def classify_market(
    close: float,
    ma20: float | None,
    ma50: float | None,
    ma200: float | None,
    *,
    previous_close: float | None,
    volume_ratio: float | None,
    rules: SignalRules = DEFAULT_RULES,
) -> tuple[MarketRegime | None, TrendState | None]:
    if ma20 is None or ma50 is None or ma200 is None:
        regime, trend = None, None
    elif close > ma200 and ma20 > ma50 > ma200:
        regime, trend = MarketRegime.TREND_UP, TrendState.STRONG_UP
    elif close < ma200 and ma20 < ma50 < ma200:
        regime, trend = MarketRegime.TREND_DOWN, TrendState.STRONG_DOWN
    elif close > ma200:
        regime, trend = MarketRegime.RANGE, TrendState.WEAK_UP
    elif close < ma200:
        regime, trend = MarketRegime.RANGE, TrendState.WEAK_DOWN
    else:
        regime, trend = MarketRegime.RANGE, TrendState.RANGE
    if (
        previous_close is not None
        and close < previous_close
        and volume_ratio is not None
        and volume_ratio >= rules.panic_volume_ratio
    ):
        regime = MarketRegime.HIGH_RISK
    return regime, trend
