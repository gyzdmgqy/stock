from shared.enums import SignalComponent
from shared.models import DailyPrice

from .evidence import ScoreResult, check
from .rules import DEFAULT_RULES, SignalRules


def score_volume_confirmation(
    bar: DailyPrice,
    *,
    previous_close: float | None,
    prior_volume_avg5: float | None,
    previous_down_volume: int | None,
    rules: SignalRules = DEFAULT_RULES,
) -> ScoreResult:
    up = (
        bar.close > previous_close
        if bar.close is not None and previous_close is not None
        else None
    )
    above_average = (
        bar.volume > prior_volume_avg5
        if bar.volume is not None and prior_volume_avg5 is not None
        else None
    )
    above_down = (
        bar.volume > previous_down_volume
        if bar.volume is not None and previous_down_volume is not None
        else None
    )
    near_high = (
        bar.high > bar.low
        and bar.high - bar.close <= rules.near_high_fraction * (bar.high - bar.low)
        if bar.high is not None and bar.low is not None and bar.close is not None
        else None
    )
    checks = (
        (
            "volume_above_avg5",
            above_average,
            f"成交量 {bar.volume} 高于此前五日均量 {prior_volume_avg5}。",
        ),
        (
            "volume_above_previous_down_day",
            above_down,
            f"成交量 {bar.volume} 高于上个下跌日的 {previous_down_volume}。",
        ),
        (
            "close_near_high",
            near_high,
            f"收盘进入振幅顶部 {rules.near_high_fraction:.0%}。",
        ),
    )
    details = (
        check(
            SignalComponent.VOLUME,
            "up_day",
            up,
            0.0,
            f"收盘 {bar.close} 高于前收 {previous_close}。",
        ),
        *(
            check(
                SignalComponent.VOLUME,
                name,
                False if up is False else passed if up else None,
                100 / 3,
                explanation,
            )
            for name, passed, explanation in checks
        ),
    )
    score = (
        None
        if any(detail.score is None for detail in details)
        else sum(detail.score for detail in details)
    )
    return ScoreResult(score, details)
