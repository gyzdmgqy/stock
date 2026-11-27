from datetime import timedelta

from shared.enums import Action, MarketRegime, OrderType, StopType, StrategyType
from shared.models.trade_plan import EntryOrder, StopOrder

from ..rules.confidence_gate import entry_confidence
from ..rules.event_risk_gate import earnings_block_reason
from ..rules.hourly_gate import hourly_block_reason
from ..rules.protective_exit_gate import required_reduction_quantity
from ..sizing.position_sizing import position_size, size_entry
from .base import Decision, PlanningContext, PortfolioState

_ENTRY_STRATEGY = StrategyType.FALSE_BREAKDOWN_REENTRY
_ENTRY_CONDITIONS = (
    "false_breakdown_score_above_70",
    "volume_confirmation_score_above_60",
    "hourly_higher_low_and_above_vwap",
    "earnings_cash_and_exposure_gates_passed",
)


def plan_active(context: PlanningContext) -> Decision:
    state = context.request.portfolio
    if state is None:
        return Decision(Action.WATCH, "缺少账户持仓和资金快照。")
    age = context.request.as_of - state.observed_at
    if (
        not timedelta(0)
        <= age
        <= timedelta(hours=context.limits.max_portfolio_age_hours)
    ):
        return Decision(Action.WATCH, "账户快照过期或晚于评估时刻。")
    if state.has_open_order is not False:
        return Decision(Action.WATCH, "存在未完成订单或订单状态未确认。")

    protective = _protective_exit(context, state)
    return protective if protective else _plan_entry(context, state)


def _protective_exit(
    context: PlanningContext, state: PortfolioState
) -> Decision | None:
    if state.quantity == 0:
        return None
    if context.confirmed_ma200_exit:
        action, quantity = Action.EXIT, state.quantity
        trigger = "two_completed_closes_below_ma200"
        reason = "连续两个已收盘交易日低于各自 MA200。"
    elif (
        quantity := required_reduction_quantity(
            state.quantity,
            state.position_value,
            state.account_equity,
            context.limits.max_single_stock_weight,
        )
    ) is not None:
        action, trigger = Action.REDUCE, "account_symbol_weight_above_cap"
        reason = "账户个股敞口超限，按持仓快照估算减至上限所需股数。"
    else:
        return None

    if state.available_to_sell is None or state.available_to_sell < quantity:
        return Decision(
            Action.WATCH,
            "保护性触发已满足，可卖股数不足或尚未确认。",
            strategy_type=StrategyType.RISK_REDUCTION,
            exit_trigger=(trigger,),
        )

    limit = context.request.exit_limit_price
    return Decision(
        action,
        reason,
        strategy_type=StrategyType.RISK_REDUCTION,
        exit_trigger=(trigger,),
        invalid_condition=(
            "protective_trigger_no_longer_valid",
            "sellable_position_changed",
        ),
        position_size=position_size(state, quantity, limit),
        order=(
            EntryOrder(type=OrderType.LIMIT, price=limit) if limit is not None else None
        ),
    )


def _plan_entry(context: PlanningContext, state: PortfolioState) -> Decision:
    signal, request, limits = context.signal, context.request, context.limits
    confidence = entry_confidence(signal)

    def watch(reason: str) -> Decision:
        return Decision(
            Action.WATCH,
            reason,
            strategy_type=_ENTRY_STRATEGY,
            confidence=confidence,
            requires_hourly=True,
        )

    if (
        not context.daily_is_current
        or context.plan_date not in request.trading_sessions
    ):
        return watch("日线信号未覆盖最近已收盘交易日，或执行日不在交易日历内。")
    if state.quantity == 0 and not request.reentry_candidate:
        return watch("无持仓且未标记为重新入场候选。")
    if confidence is None or confidence < max(
        70, limits.min_entry_confidence_for_order_draft
    ):
        return watch("入场置信度缺失或低于门槛。")
    if signal.market_regime not in (MarketRegime.TREND_UP, MarketRegime.RANGE):
        return watch("日线状态未满足当前假跌破入场规则。")
    if (
        signal.false_breakdown_score is None
        or signal.false_breakdown_score <= 70
        or signal.volume_confirmation_score is None
        or signal.volume_confirmation_score <= 60
    ):
        return watch("假跌破或成交量确认分数未通过策略门槛。")
    blocker = earnings_block_reason(context) or hourly_block_reason(context)
    if blocker:
        return watch(blocker)
    prices = request.entry_prices
    if prices is None or prices.risk_reward < limits.min_risk_reward_ratio:
        return watch("缺少入场、止损参考和目标价格，或计划盈亏比不足。")
    size, sizing_blocker = size_entry(state, prices, limits)
    if sizing_blocker:
        return watch(sizing_blocker)

    return Decision(
        Action.ADD if state.quantity > 0 else Action.RE_ENTRY,
        "日线形态、小时确认、财报和仓位风控均通过，等待人工审核。",
        strategy_type=_ENTRY_STRATEGY,
        confidence=confidence,
        entry_condition=_ENTRY_CONDITIONS,
        invalid_condition=(
            "hourly_confirmation_expired_or_reversed",
            "close_below_ma200_for_2_completed_sessions",
            "entry_prices_or_risk_limits_no_longer_valid",
        ),
        order=EntryOrder(type=OrderType.LIMIT, price=prices.limit_price),
        stop=StopOrder(
            type=StopType.STRUCTURE_CONFIRMATION,
            stop_price=prices.stop_price,
            condition="close_below_ma200_for_2_completed_sessions",
            reason="止损参考价用于估算单笔风险，退出按结构条件。",
        ),
        position_size=size,
        target_price=prices.target_price,
        risk_reward_ratio=float(prices.risk_reward),
        requires_hourly=True,
    )
