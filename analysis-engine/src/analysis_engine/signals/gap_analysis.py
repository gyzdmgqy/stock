from shared.enums import GapDirection, GapType
from shared.models import DailyPrice

from .rules import DEFAULT_RULES, SignalRules


def analyze_gap(
    bar: DailyPrice,
    *,
    previous_close: float | None,
    volume_ratio: float | None,
    rules: SignalRules = DEFAULT_RULES,
) -> tuple[GapType | None, GapDirection | None, float | None]:
    if previous_close is None or bar.open is None:
        return None, None, None
    gap = (bar.open - previous_close) * 100 / previous_close
    if abs(gap) < rules.material_gap_percent:
        return GapType.NONE, GapDirection.NONE, gap
    if gap > 0:
        return None, GapDirection.UP, gap
    if bar.close is not None and bar.close >= previous_close:
        return GapType.SHAKEOUT, GapDirection.DOWN, gap
    if volume_ratio is not None and volume_ratio >= rules.panic_volume_ratio:
        return GapType.PANIC, GapDirection.DOWN, gap
    return None, GapDirection.DOWN, gap
