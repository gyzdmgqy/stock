import json
from hashlib import sha256
from pathlib import Path

import yaml
from duckdb import DuckDBPyConnection

from shared.db import get_trade_plan, insert_trade_plan
from shared.db.database import DEFAULT_CONFIG_DIR
from shared.enums import AccountRole, Action, Broker, OrderInstruction, TradePlanStatus
from shared.models import DailySignal, TradePlan

from ..planners.base import (
    AccountPolicy,
    AssetType,
    Decision,
    OrderIntent,
    PlanningContext,
    PlanningRequest,
    PlanningResult,
    RiskLimits,
)
from ..planners.schwab_active_planner import plan_active
from ..planners.vanguard_exit_planner import plan_exit_only
from ..rules.account_role_gate import is_exit_only_stock, supports_active_trading
from ..rules.hourly_gate import APP_TIMEZONE
from ..rules.protective_exit_gate import completed_sessions, two_closes_below_ma200

RULE_VERSION = "phase5-v2"
_PLAN_INVALIDATION = "source_signal_or_account_state_changed"
_INERT_STATUSES = {
    TradePlanStatus.REJECTED,
    TradePlanStatus.EXPIRED,
    TradePlanStatus.EXECUTED,
}


class TradePlanService:
    def __init__(
        self,
        db: DuckDBPyConnection,
        *,
        limits: RiskLimits | None = None,
        config_dir: Path = DEFAULT_CONFIG_DIR,
    ) -> None:
        self._db = db
        if limits is None:
            settings = yaml.safe_load(
                (config_dir / "risk.yaml").read_text(encoding="utf-8")
            )
            limits = RiskLimits.model_validate(settings["risk"])
        self._limits = RiskLimits.model_validate(limits.model_dump())

    def generate_trade_plan(self, request: PlanningRequest) -> PlanningResult:
        request = PlanningRequest.model_validate(request.model_dump())
        self._db.begin()
        try:
            context = self._load_context(request)
            decision = _decide(context)
            plan = self._persist(context, decision)
            intent = _order_intent(context, plan)
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return PlanningResult(plan, intent)

    def _load_context(self, request: PlanningRequest) -> PlanningContext:
        signal = DailySignal.model_validate(
            self._required_row(
                "daily_signal",
                "signal_id",
                request.signal_id,
                tuple(DailySignal.model_fields),
            )
        )
        columns = tuple(AccountPolicy.model_fields)
        account_row = self._required_row(
            "portfolio_account", "account_id", request.account_id, columns
        )
        if account_row["default_replacement"] is not None:
            account_row["default_replacement"] = json.loads(
                account_row["default_replacement"]
            )
        account = AccountPolicy.model_validate(account_row)
        if request.portfolio is not None and (
            request.portfolio.account_id != account.account_id
            or request.portfolio.symbol != signal.symbol
        ):
            raise ValueError("账户快照的账户或标的与信号不一致")

        symbol = self._required_row(
            "symbol", "symbol", signal.symbol, ("asset_type", "is_active")
        )
        asset_type: AssetType | None = (
            symbol["asset_type"]
            if symbol["is_active"]
            and symbol["asset_type"] in ("STOCK", "ETF", "INDEX", "CASH")
            else None
        )
        local = request.as_of.astimezone(APP_TIMEZONE)
        completed = completed_sessions(
            request.trading_sessions, request.as_of, request.session_close
        )
        current = bool(completed and signal.trade_date == completed[-1])
        earnings = tuple(
            day
            for (day,) in self._db.execute(
                "SELECT DISTINCT event_date FROM corporate_event WHERE symbol = ? "
                "AND event_type = 'EARNINGS' AND event_date >= ? ORDER BY event_date",
                [signal.symbol, local.date()],
            ).fetchall()
        )
        return PlanningContext(
            request=request,
            signal=signal,
            account=account,
            plan_date=local.date(),
            asset_type=asset_type,
            daily_is_current=current,
            earnings_dates=earnings,
            confirmed_ma200_exit=(
                current
                and len(completed) >= 2
                and two_closes_below_ma200(self._db, signal.symbol, completed[-2:])
            ),
            future_reentry_account=self._future_reentry_account(account, asset_type),
            limits=self._limits,
        )

    def _required_row(
        self, table: str, key: str, value: str, columns: tuple[str, ...]
    ) -> dict:
        row = self._db.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {key} = ?", [value]
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到 {key} 对应的记录：{value}")
        return dict(zip(columns, row, strict=True))

    def _future_reentry_account(
        self, account: AccountPolicy, asset: AssetType | None
    ) -> str | None:
        if account.broker is not Broker.VANGUARD or not is_exit_only_stock(
            account, asset
        ):
            return None
        row = self._db.execute("""
            SELECT account_id FROM portfolio_account WHERE account_id = 'SCHWAB_ROTH'
            AND broker = 'SCHWAB' AND account_role = 'ACTIVE_TRADING'
            AND individual_stock_policy = 'ACTIVE_ALLOWED' AND is_active
            """).fetchone()
        return row[0] if row else None

    def _persist(self, context: PlanningContext, decision: Decision) -> TradePlan:
        candidate = _make_plan(context, decision)
        saved = get_trade_plan(self._db, candidate.plan_id)
        if saved is None:
            previous = self._db.execute(
                "SELECT plan_id FROM trade_plan WHERE account_id = ? AND symbol = ? AND plan_date = ? "
                "ORDER BY created_at DESC NULLS LAST, plan_id DESC LIMIT 1",
                [candidate.account_id, candidate.symbol, candidate.plan_date],
            ).fetchone()
            if previous:
                candidate.supersedes_plan_id = previous[0]
            insert_trade_plan(self._db, candidate)
            saved = get_trade_plan(self._db, candidate.plan_id)
        if saved is None:
            raise RuntimeError("写入后无法读回交易计划")
        self._db.execute(
            "INSERT INTO trade_plan_signal_link (plan_id, signal_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            [saved.plan_id, context.signal.signal_id],
        )
        return saved


def _decide(context: PlanningContext) -> Decision:
    account, state = context.account, context.request.portfolio
    if not account.is_active or account.base_currency != "USD":
        return Decision(Action.WATCH, "账户未启用或净值币种不适用。")
    if is_exit_only_stock(account, context.asset_type):
        if state is not None and not (
            0
            <= (context.request.as_of - state.observed_at).total_seconds()
            <= context.limits.max_portfolio_age_hours * 3600
        ):
            return Decision(Action.WATCH, "需要刷新退出专用账户的持仓快照。")
        return plan_exit_only(context)
    if supports_active_trading(account, context.asset_type):
        return plan_active(context)
    if context.asset_type == "ETF" and account.account_role is AccountRole.CORE_PASSIVE:
        return Decision(Action.HOLD, "核心 ETF 等待单独的择时规则。")
    return Decision(Action.WATCH, "账户角色或标的类型未开放此策略。")


def _make_plan(context: PlanningContext, decision: Decision) -> TradePlan:
    request, signal, account = context.request, context.signal, context.account
    references = {
        "daily_signal_id": signal.signal_id,
        "intraday_signal_id": (
            request.intraday_signal.signal_id if request.intraday_signal else None
        ),
        "intraday_signal": (
            request.intraday_signal.model_dump(mode="json")
            if request.intraday_signal
            else None
        ),
        "portfolio_state": (
            request.portfolio.model_dump(mode="json") if request.portfolio else None
        ),
        "trading_sessions": [day.isoformat() for day in request.trading_sessions],
        "session_close": (
            request.session_close.isoformat() if request.session_close else None
        ),
        "portfolio_observed_at": (
            request.portfolio.observed_at.isoformat() if request.portfolio else None
        ),
        "earnings_checked_through": (
            request.earnings_checked_through.isoformat()
            if request.earnings_checked_through
            else None
        ),
        "earnings_dates": [day.isoformat() for day in context.earnings_dates],
        "confirmed_ma200_exit": context.confirmed_ma200_exit,
        "risk_limits": context.limits.model_dump(mode="json"),
    }
    candidate = TradePlan(
        plan_id="pending",
        symbol=signal.symbol,
        account_id=account.account_id,
        account_role=account.account_role,
        plan_date=context.plan_date,
        action=decision.action,
        reason=decision.reason,
        strategy_type=decision.strategy_type,
        confidence=decision.confidence,
        execution_timeframe="1h" if decision.requires_hourly else None,
        rule_version=RULE_VERSION,
        input_references=references,
        entry_condition=list(decision.entry_condition),
        invalid_condition=[_PLAN_INVALIDATION, *decision.invalid_condition],
        exit_trigger=list(decision.exit_trigger),
        entry_order=decision.order,
        stop_order=decision.stop,
        position_size=decision.position_size,
        target_price_1=decision.target_price,
        risk_reward_ratio=decision.risk_reward_ratio,
        replacement=decision.replacement,
        future_reentry_account=decision.future_reentry_account,
    )
    fingerprint = json.dumps(
        (
            candidate.model_dump(mode="json"),
            request.model_dump(mode="json", exclude={"as_of"}),
            signal.model_dump(mode="json", exclude={"created_at"}),
            account.model_dump(mode="json"),
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    suffix = sha256(fingerprint.encode()).hexdigest()[:16]
    candidate.plan_id = (
        f"TP-{context.plan_date:%Y%m%d}-{account.account_id}-{signal.symbol}-{suffix}"
    )
    return candidate


def _order_intent(context: PlanningContext, plan: TradePlan) -> OrderIntent | None:
    buy = plan.action in (Action.ADD, Action.RE_ENTRY)
    sell = plan.action in (Action.REDUCE, Action.EXIT)
    if (
        not (buy or sell)
        or not context.account.order_draft_enabled
        or context.plan_date not in context.request.trading_sessions
        or plan.status in _INERT_STATUSES
        or plan.entry_order is None
        or plan.entry_order.price is None
        or plan.position_size is None
        or plan.position_size.quantity is None
    ):
        return None
    return OrderIntent(
        plan_id=plan.plan_id,
        account_id=plan.account_id,
        symbol=plan.symbol,
        instruction=OrderInstruction.BUY if buy else OrderInstruction.SELL,
        limit_price=plan.entry_order.price,
        quantity=plan.position_size.quantity,
    )
