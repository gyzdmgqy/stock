from ..planners.base import PlanningContext


def earnings_block_reason(context: PlanningContext) -> str | None:
    if context.asset_type != "STOCK":
        return None

    request = context.request
    sessions = request.trading_sessions
    day = context.plan_date
    if day not in sessions:
        return "缺少执行交易日的日历。"
    end_index = (
        sessions.index(day) + context.limits.block_new_entry_before_earnings_days
    )
    if end_index >= len(sessions):
        return "交易日历未覆盖完整财报窗口。"

    end = sessions[end_index]
    if any(day <= event <= end for event in context.earnings_dates):
        return "执行日或其后的禁入交易日窗口内有财报。"
    if (
        request.earnings_checked_through is None
        or request.earnings_checked_through < end
    ):
        return "财报日历覆盖不足，无法判断入场窗口。"
    return None
