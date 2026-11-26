from shared.enums import SignalComponent
from shared.models import DailyPrice

from .evidence import ScoreResult, check
from .rules import DEFAULT_RULES, SignalRules


def lower_shadow_fraction(bar: DailyPrice) -> float | None:
    if bar.open is None or bar.close is None or bar.low is None or bar.high is None:
        return None
    span = bar.high - bar.low
    return (min(bar.open, bar.close) - bar.low) / span if span else 0.0


def score_false_breakdown(
    bar: DailyPrice,
    ma200: float | None,
    prior_volume_avg5: float | None,
    *,
    intraday_low: float | None = None,
    rules: SignalRules = DEFAULT_RULES,
) -> ScoreResult:
    lows = [value for value in (bar.low, intraday_low) if value is not None]
    low = min(lows, default=None)
    shadow = lower_shadow_fraction(bar)
    ratio = (
        bar.volume / prior_volume_avg5
        if bar.volume is not None
        and prior_volume_avg5 is not None
        and prior_volume_avg5 > 0
        else None
    )
    breach = low < ma200 if low is not None and ma200 is not None else None
    recovered = (
        bar.close > ma200 if bar.close is not None and ma200 is not None else None
    )
    long_shadow = shadow >= rules.lower_shadow_min if shadow is not None else None
    calm = ratio < rules.panic_volume_ratio if ratio is not None else None

    checks = (
        ("low_below_ma200", breach, f"有效最低价 {low} 低于此前 MA200 {ma200}。"),
        (
            "close_back_above_ma200",
            recovered,
            f"收盘 {bar.close} 回到此前 MA200 {ma200} 上方。",
        ),
        (
            "long_lower_shadow",
            long_shadow,
            f"下影线占振幅 {shadow}，下限 {rules.lower_shadow_min}。",
        ),
        (
            "volume_below_panic",
            calm,
            f"成交量为此前均量的 {ratio} 倍，恐慌量阈值 {rules.panic_volume_ratio}。",
        ),
    )
    outcomes = (breach, recovered, long_shadow, calm)
    complete = None if None in outcomes else all(outcomes)
    details = tuple(
        check(SignalComponent.BREAKDOWN, name, passed, 20.0, explanation)
        for name, passed, explanation in (
            *checks,
            ("false_breakdown_confirmed", complete, "四项条件均通过时加 20 分。"),
        )
    )
    score = None if complete is None else sum(detail.score or 0.0 for detail in details)
    return ScoreResult(score, details)
