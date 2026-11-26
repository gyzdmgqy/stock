from datetime import timedelta
from zoneinfo import ZoneInfo

from ..planners.base import PlanningContext

APP_TIMEZONE = ZoneInfo("America/Chicago")


def hourly_block_reason(context: PlanningContext) -> str | None:
    request = context.request
    signal = request.intraday_signal
    if (
        signal is None
        or signal.symbol != context.signal.symbol
        or signal.trade_date != context.plan_date
        or signal.bar_start.astimezone(APP_TIMEZONE).date() != context.plan_date
    ):
        return "缺少同标的、同执行日的一小时确认。"

    bar_end = signal.bar_start + timedelta(hours=1)
    age = request.as_of - bar_end
    if (
        not timedelta(0)
        <= age
        <= timedelta(minutes=context.limits.max_hourly_age_minutes)
    ):
        return "一小时确认尚未收盘或已经过期。"
    if (
        signal.hourly_trend != "HIGHER_LOW_CONFIRMED"
        or signal.vwap_status != "ABOVE_VWAP"
    ):
        return "一小时级别尚未同时确认更高低点及站上 VWAP。"
    return None
