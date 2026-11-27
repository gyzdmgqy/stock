from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from shared.models import IntradaySignal

from ..planners.base import PlanningContext

APP_TIMEZONE = ZoneInfo("America/Chicago")


def hourly_block_reason(context: PlanningContext) -> str | None:
    return hourly_confirmation_block_reason(
        context.request.intraday_signal,
        symbol=context.signal.symbol,
        day=context.plan_date,
        as_of=context.request.as_of,
        max_age_minutes=context.limits.max_hourly_age_minutes,
    )


def hourly_confirmation_block_reason(
    signal: IntradaySignal | None,
    *,
    symbol: str,
    day: date,
    as_of: datetime,
    max_age_minutes: int,
) -> str | None:
    if (
        signal is None
        or signal.symbol != symbol
        or signal.trade_date != day
        or signal.bar_start.astimezone(APP_TIMEZONE).date() != day
    ):
        return "缺少同标的、同执行日的一小时确认。"

    bar_end = signal.bar_start + timedelta(hours=1)
    age = as_of - bar_end
    if not timedelta(0) <= age <= timedelta(minutes=max_age_minutes):
        return "一小时确认尚未收盘或已经过期。"
    if (
        signal.hourly_trend != "HIGHER_LOW_CONFIRMED"
        or signal.vwap_status != "ABOVE_VWAP"
    ):
        return "一小时级别尚未同时确认更高低点及站上 VWAP。"
    return None
