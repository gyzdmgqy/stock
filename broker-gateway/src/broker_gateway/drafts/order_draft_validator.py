from datetime import date, datetime, timedelta
from decimal import Decimal

from duckdb import DuckDBPyConnection
from pydantic import BaseModel, ConfigDict

from shared.enums import (
    Action,
    ErrorType,
    OrderInstruction,
    OrderType,
    StrategyType,
    TradePlanStatus,
)
from shared.models import DailySignal, IntradaySignal, OrderSnapshot, TradePlan
from trade_planner.planners.base import (
    AccountPolicy,
    EntryPrices,
    PortfolioState,
    RiskLimits,
)
from trade_planner.rules.account_role_gate import (
    is_exit_only_stock,
    supports_active_trading,
)
from trade_planner.rules.confidence_gate import entry_confidence
from trade_planner.rules.hourly_gate import (
    APP_TIMEZONE,
    hourly_confirmation_block_reason,
)
from trade_planner.rules.protective_exit_gate import (
    completed_sessions,
    required_reduction_quantity,
    two_closes_below_ma200,
)
from trade_planner.sizing.position_sizing import size_entry

_BUY_ACTIONS = {Action.ADD, Action.RE_ENTRY}
_SELL_ACTIONS = {Action.REDUCE, Action.EXIT}
_REVIEWABLE = {
    TradePlanStatus.DRAFT,
    TradePlanStatus.REVIEWED,
    TradePlanStatus.APPROVED,
}


class DraftError(ValueError):
    def __init__(self, code: ErrorType, message: str) -> None:
        self.code = code
        super().__init__(message)


def _blocked(message: str) -> DraftError:
    return DraftError(ErrorType.RISK_RULE_BLOCKED, message)


class _Evidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    daily_signal_id: str | None = None
    intraday_signal_id: str | None = None
    intraday_signal: IntradaySignal | None = None
    portfolio_state: PortfolioState | None = None
    trading_sessions: tuple[date, ...] = ()
    earnings_checked_through: date | None = None


class OrderDraftValidator:
    def __init__(self, db: DuckDBPyConnection, limits: RiskLimits) -> None:
        self._db = db
        self._limits = limits

    def baseline(self, plan: TradePlan, as_of: datetime) -> OrderSnapshot:
        if plan.action not in _BUY_ACTIONS | _SELL_ACTIONS:
            raise _blocked("计划行动不允许生成订单草稿。WATCH 不生成条件草稿。")
        if plan.status not in _REVIEWABLE or not plan.invalid_condition:
            raise _blocked("计划已失效或缺少失效条件。")
        if plan.plan_date != as_of.astimezone(APP_TIMEZONE).date():
            raise _blocked("只允许使用芝加哥业务日期为当天的计划。")
        if self._db.execute(
            "SELECT 1 FROM trade_plan WHERE supersedes_plan_id = ? LIMIT 1",
            [plan.plan_id],
        ).fetchone():
            raise _blocked("计划已被替代，请审阅当前计划。")

        row = self._db.execute(
            "SELECT asset_type FROM symbol WHERE symbol = ? AND is_active",
            [plan.symbol],
        ).fetchone()
        asset = row[0] if row else None
        account = self._account(plan.account_id)
        buy = plan.action in _BUY_ACTIONS
        if buy and is_exit_only_stock(account, asset):
            raise _blocked("账户政策禁止个股买入。")
        if not (
            account.account_role is plan.account_role
            and account.order_draft_enabled
            and account.base_currency == "USD"
            and supports_active_trading(account, asset)
        ):
            raise _blocked("账户、标的类型或草稿权限不允许此操作。")
        if buy and (
            plan.confidence is None
            or plan.confidence
            < max(70, self._limits.min_entry_confidence_for_order_draft)
        ):
            raise _blocked("入场置信度缺失或低于门槛。")
        order, size = plan.entry_order, plan.position_size
        if order is None or order.type is not OrderType.LIMIT or order.price is None:
            raise _blocked("首版仅转换有明确限价的计划。")
        if size is None or size.quantity is None:
            raise _blocked("计划没有有效的下单数量。")
        return OrderSnapshot(
            broker=account.broker,
            account_id=account.account_id,
            symbol=plan.symbol,
            instruction=OrderInstruction.BUY if buy else OrderInstruction.SELL,
            order_type=OrderType.LIMIT,
            quantity=size.quantity,
            limit_price=order.price,
            time_in_force="DAY",
            session="NORMAL",
        )

    def validate(
        self,
        plan: TradePlan,
        order: OrderSnapshot,
        baseline: OrderSnapshot,
        as_of: datetime,
        *,
        approving: bool = False,
    ) -> None:
        dimensions = set(OrderSnapshot.model_fields) - {"quantity", "limit_price"}
        if order.model_dump(include=dimensions) != baseline.model_dump(
            include=dimensions
        ):
            raise _blocked("草稿的账户、标的、方向或执行方式与交易计划不匹配。")
        if order.instruction is OrderInstruction.BUY:
            if (
                order.quantity > baseline.quantity
                or order.limit_price > baseline.limit_price
            ):
                raise _blocked("买入修改不可超过计划的股数或抬高限价。")
        elif (
            order.quantity != baseline.quantity
            or order.limit_price < baseline.limit_price
        ):
            raise _blocked("保护性卖出须保持计划股数，且不可降低计划限价。")

        refs = _Evidence.model_validate(plan.input_references or {})
        if (
            plan.execution_timeframe == "1h"
            or plan.strategy_type is StrategyType.FALSE_BREAKDOWN_REENTRY
            or any("hourly" in value.casefold() for value in plan.entry_condition)
        ):
            signal = refs.intraday_signal
            if signal is not None and signal.signal_id != refs.intraday_signal_id:
                raise _blocked("一小时证据与交易计划引用不一致。")
            reason = hourly_confirmation_block_reason(
                signal,
                symbol=plan.symbol,
                day=plan.plan_date,
                as_of=as_of,
                max_age_minutes=self._limits.max_hourly_age_minutes,
            )
            if reason:
                raise _blocked(reason)
        elif plan.execution_timeframe not in (None, "daily"):
            raise _blocked("无法复核该执行周期的确认条件。")

        sessions = refs.trading_sessions
        if plan.plan_date not in sessions or tuple(sorted(set(sessions))) != sessions:
            raise _blocked("缺少有效的执行交易日历，请重新生成计划。")
        state = refs.portfolio_state
        if (
            state is None
            or (state.account_id, state.symbol) != (plan.account_id, plan.symbol)
            or not self._fresh(state.observed_at, as_of)
            or state.has_open_order is not False
        ):
            raise _blocked("账户快照缺失、过期、归属不一致或未确认挂单状态。")
        value = self._check_latest_position(order, state, as_of)
        if order.instruction is OrderInstruction.BUY:
            self._validate_entry(plan, order, refs, state, value, as_of, approving)
        else:
            self._validate_exit(plan, order, refs, state, value, as_of)

    def _account(self, account_id: str) -> AccountPolicy:
        columns = tuple(
            name for name in AccountPolicy.model_fields if name != "default_replacement"
        )
        row = self._db.execute(
            f"SELECT {', '.join(columns)} FROM portfolio_account WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None:
            raise DraftError(ErrorType.DATA_MISSING, "找不到计划的账户。")
        return AccountPolicy.model_validate(dict(zip(columns, row, strict=True)))

    def _fresh(self, observed_at: datetime, as_of: datetime) -> bool:
        return (
            timedelta(0)
            <= as_of - observed_at
            <= timedelta(hours=self._limits.max_portfolio_age_hours)
        )

    def _check_latest_position(
        self, order: OrderSnapshot, state: PortfolioState, as_of: datetime
    ) -> Decimal | None:
        row = self._db.execute(
            """
            SELECT TRY_CAST(quantity AS DECIMAL(20, 8)), TRY_CAST(market_value AS DECIMAL(20, 6))
            FROM portfolio_position_snapshot
            WHERE account_id = ? AND symbol = ? AND observed_at >= ? AND observed_at <= ?
            ORDER BY observed_at DESC, created_at DESC NULLS LAST, snapshot_id DESC
            LIMIT 1
            """,
            [order.account_id, order.symbol, state.observed_at, as_of],
        ).fetchone()
        if row is None:
            return state.position_value
        quantity, market_value = row
        if order.instruction is OrderInstruction.SELL and (
            quantity is None or quantity < order.quantity
        ):
            raise DraftError(
                ErrorType.INSUFFICIENT_POSITION, "最新持仓无法覆盖卖出数量。"
            )
        if quantity != state.quantity:
            raise _blocked("持仓已不同于计划快照，请重新生成计划。")
        return market_value if market_value is not None else state.position_value

    def _available_cash(self, state: PortfolioState, as_of: datetime) -> Decimal | None:
        latest = self._db.execute(
            """
            SELECT available_to_trade FROM portfolio_cash_snapshot
            WHERE account_id = ? AND currency = 'USD' AND observed_at >= ? AND observed_at <= ?
            ORDER BY observed_at DESC, created_at DESC NULLS LAST, snapshot_id DESC LIMIT 1
            """,
            [state.account_id, state.observed_at, as_of],
        ).fetchone()
        return latest[0] if latest is not None else state.available_cash

    def _validate_entry(
        self,
        plan: TradePlan,
        order: OrderSnapshot,
        refs: _Evidence,
        state: PortfolioState,
        value: Decimal | None,
        as_of: datetime,
        approving: bool,
    ) -> None:
        self._check_entry_source(plan, refs, as_of)
        cost = order.quantity * order.limit_price
        available = self._available_cash(state, as_of)
        if available is not None and available < cost:
            raise DraftError(
                ErrorType.INSUFFICIENT_CASH, "可交易现金低于订单估算金额。"
            )
        if available is None and approving:
            raise DraftError(ErrorType.DATA_MISSING, "批准买入需要可验证的可交易现金。")

        if (
            plan.stop_order is None
            or plan.stop_order.stop_price is None
            or plan.target_price_1 is None
        ):
            raise _blocked("缺少入场风险复核所需的止损参考或目标价。")
        prices = EntryPrices(
            limit_price=order.limit_price,
            stop_price=plan.stop_order.stop_price,
            target_price=plan.target_price_1,
        )
        if prices.risk_reward < self._limits.min_risk_reward_ratio:
            raise _blocked("订单参数未达到最低盈亏比。")
        if order.quantity != order.quantity.to_integral_value():
            raise _blocked("当前入场规划仅支持整数股。")
        # 用草稿金额作为计算的预算上限，资金是否可用已单独校验。
        risk_state = PortfolioState.model_validate(
            {
                **state.model_dump(),
                "available_cash": cost,
                "position_value": value,
            }
        )
        size, reason = size_entry(risk_state, prices, self._limits)
        if size is None or size.quantity < order.quantity:
            raise _blocked(reason or "当前订单数量超出仓位或单笔风险上限。")

    def _check_entry_source(
        self, plan: TradePlan, refs: _Evidence, as_of: datetime
    ) -> None:
        completed = completed_sessions(refs.trading_sessions, as_of)
        columns = tuple(DailySignal.model_fields)
        row = self._db.execute(
            f"SELECT {', '.join('s.' + col for col in columns)} FROM daily_signal s "
            "JOIN trade_plan_signal_link l USING (signal_id) "
            "WHERE l.plan_id = ? AND s.signal_id = ? AND s.symbol = ?",
            [plan.plan_id, refs.daily_signal_id, plan.symbol],
        ).fetchone()
        if row is None or not completed:
            raise _blocked("缺少与计划关联的已收盘日线信号。")
        source = DailySignal.model_validate(dict(zip(columns, row, strict=True)))
        if source.trade_date != completed[-1]:
            raise _blocked("计划的日线信号已不是最近收盘交易日。")
        latest = self._db.execute(
            "SELECT signal_id FROM daily_signal WHERE symbol = ? AND trade_date = ? "
            "ORDER BY created_at DESC NULLS LAST, signal_id DESC LIMIT 1",
            [plan.symbol, source.trade_date],
        ).fetchone()
        if latest != (source.signal_id,):
            raise _blocked("日线信号已有新版本，请重新生成计划。")
        floor = max(70, self._limits.min_entry_confidence_for_order_draft)
        score = entry_confidence(source)
        if score is None or score < floor:
            raise _blocked("源信号的入场置信度不再满足门槛。")
        if plan.strategy_type is StrategyType.FALSE_BREAKDOWN_REENTRY and (
            source.market_regime not in ("TREND_UP", "RANGE")
            or (source.false_breakdown_score or 0) <= 70
            or (source.volume_confirmation_score or 0) <= 60
        ):
            raise _blocked("关联日线不再满足假跌破和成交量条件。")
        if (
            self._db.execute(
                "SELECT 1 FROM symbol WHERE symbol = ? AND asset_type = 'STOCK'",
                [plan.symbol],
            ).fetchone()
            is None
        ):
            return
        end_index = (
            refs.trading_sessions.index(plan.plan_date)
            + self._limits.block_new_entry_before_earnings_days
        )
        if end_index >= len(refs.trading_sessions):
            raise _blocked("交易日历未覆盖入场财报窗口。")
        end = refs.trading_sessions[end_index]
        if refs.earnings_checked_through is None or refs.earnings_checked_through < end:
            raise _blocked("财报数据未覆盖完整入场窗口。")
        if self._db.execute(
            "SELECT 1 FROM corporate_event WHERE symbol = ? AND event_type = 'EARNINGS' "
            "AND event_date BETWEEN ? AND ? LIMIT 1",
            [plan.symbol, plan.plan_date, end],
        ).fetchone():
            raise _blocked("财报禁入窗口内有事件，不能生成或批准买入订单。")

    def _validate_exit(
        self,
        plan: TradePlan,
        order: OrderSnapshot,
        refs: _Evidence,
        state: PortfolioState,
        value: Decimal | None,
        as_of: datetime,
    ) -> None:
        if plan.action is Action.EXIT:
            days = completed_sessions(refs.trading_sessions, as_of)[-2:]
            if (
                "two_completed_closes_below_ma200" not in plan.exit_trigger
                or not two_closes_below_ma200(self._db, plan.symbol, days)
            ):
                raise _blocked("未验证连续两个已收盘交易日低于 MA200。")
            required = state.quantity
        else:
            required = required_reduction_quantity(
                state.quantity,
                value,
                state.account_equity,
                self._limits.max_single_stock_weight,
            )
            if (
                "account_symbol_weight_above_cap" not in plan.exit_trigger
                or required is None
            ):
                raise _blocked("未验证账户个股仓位超限的减仓触发。")
        if state.available_to_sell is None or order.quantity > min(
            state.quantity, state.available_to_sell
        ):
            raise DraftError(ErrorType.INSUFFICIENT_POSITION, "缺少充足的可卖股数。")
        if order.quantity != required:
            raise _blocked("卖出股数已与本次退出或减仓触发不一致。")
