from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import TypeVar
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from duckdb import Error as DuckDBError
from yaml import YAMLError

from broker_gateway.drafts import DraftError
from shared.db import connect_database
from shared.enums import ApprovalDecision as Decision
from shared.enums import OrderDraftStatus
from shared.models import OrderDraft

from .dashboard_approvals import DashboardApprovalService, read_config
from .dashboard_queries import DashboardQueries

_DB_LOCK = RLock()
_LOCAL_ZONE = ZoneInfo("America/Chicago")
_T = TypeVar("_T")
_STATUS = {
    "PENDING_REVIEW": "待审",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
    "DEFERRED": "已延期",
    "MODIFIED": "已替换",
    "EXPIRED": "已过期",
}
_ACTIONS = {
    "WATCH": "观察",
    "HOLD": "持有",
    "AVOID": "回避",
    "ADD": "加仓",
    "RE_ENTRY": "重新入场",
    "REDUCE": "减仓",
    "EXIT": "退出",
    "EXIT_ONLY": "仅监控退出",
}
_REGIMES = {
    "TREND_UP": "上行",
    "TREND_DOWN": "下行",
    "RANGE": "震荡",
    "HIGH_RISK": "高风险",
}
_REPORTS = {"WEEKLY": "周度", "MONTHLY": "月度"}
_ENTRY_TYPES = {
    "DAILY": "每日简报",
    "SIGNAL_REVIEW": "信号复核",
    "TRADE_PLAN_REVIEW": "计划复核",
    "ORDER_REVIEW": "订单审阅",
    "TRADE_EXECUTION": "成交记录",
    "MANUAL_NOTE": "人工备注",
}
_DRAFT_COLUMNS = {
    "symbol": "标的",
    "account_id": "账户",
    "instruction": "方向",
    "order_type": "订单类型",
    "quantity": "股数",
    "limit_price": "限价",
    "status": "状态",
    "plan_date": "业务日期",
}


@dataclass(frozen=True)
class DashboardData:
    path: Path
    config_dir: Path

    def read(self, query: Callable[[DashboardQueries], _T]) -> _T:
        with _DB_LOCK, connect_database(self._existing_path(), read_only=True) as db:
            return query(DashboardQueries(db))

    def review(
        self, draft: OrderDraft, decision: Decision | None, note: str = ""
    ) -> None:
        with _DB_LOCK, connect_database(self._existing_path()) as db:
            service = DashboardApprovalService(db, config_dir=self.config_dir)
            if decision is None:
                service.reopen(draft)
            else:
                service.decide(draft, decision, note=note)

    def _existing_path(self) -> Path:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        return self.path


def _today() -> date:
    return datetime.now(UTC).astimezone(_LOCAL_ZONE).date()


def _time(value: datetime | None) -> str:
    return (
        value.astimezone(_LOCAL_ZONE).strftime("%Y-%m-%d %H:%M %Z")
        if value
        else "未记录"
    )


def _number(value) -> str:
    return "未记录" if value is None else str(value)


def _money(value) -> str:
    return "未记录" if value is None else "$" + f"{Decimal(str(value)):,.2f}"


def _pct(value) -> str:
    return "未记录" if value is None else f"{value:.1%}"


def _heading(title: str, section: str) -> None:
    st.caption(f"PERSONAL CIO  /  {section}")
    st.title(title)


def _day(data: DashboardData, key: str, *, include_all: bool = False) -> date | None:
    days = [day for day in data.read(lambda q: q.dates(key)) if day <= _today()]
    if include_all:
        days.insert(0, None)
    if not days:
        st.info("这个视图暂无记录。")
        return None
    return st.selectbox(
        "业务日期",
        days,
        format_func=lambda day: day.isoformat() if day else "全部日期",
        key=f"{key}_date",
    )


def _account(data: DashboardData, key: str) -> str | None:
    ids = data.read(lambda q: [item["account_id"] for item in q.accounts()])
    return st.selectbox(
        "账户",
        [None, *ids],
        format_func=lambda value: value or "全部账户",
        key=f"{key}_account",
    )


def _table(
    rows: list[dict], columns: dict[str, str], *, empty: str = "暂无记录"
) -> None:
    if not rows:
        st.caption(empty)
        return

    def display(key, value):
        if isinstance(value, datetime):
            return _time(value)
        if isinstance(value, Decimal):
            return str(value)
        if key in ("status", "decision"):
            return _STATUS.get(value, value)
        if key == "action":
            return _ACTIONS.get(value, value)
        if key == "entry_type":
            return _ENTRY_TYPES.get(value, value)
        if key == "review_type":
            return _REPORTS.get(value, value)
        return value

    frame = [
        {label: display(key, row.get(key)) for key, label in columns.items()}
        for row in rows
    ]
    st.dataframe(frame, hide_index=True, width="stretch")


def _text_list(items) -> None:
    for item in items:
        st.text(f"• {item}")


def brief(data: DashboardData) -> None:
    head, date_field = st.columns([3, 1], vertical_alignment="center")
    with head:
        _heading("每日 CIO 简报", "总览")
    with date_field:
        day = _day(data, "brief")
    if day is None:
        return
    report, rows = data.read(lambda q: (q.brief(day), q.benchmark_prices(day)))
    if report is None:
        st.info("该日暂无简报。")
        return
    st.caption(f"简报生成时间 · {_time(report.created_at)}")
    risk = report.risk_summary
    metrics = st.columns(4)
    metrics[0].metric(
        "组合净值",
        _money(
            report.portfolio_summary.total_value if report.portfolio_summary else None
        ),
    )
    regime = report.market_summary.market_regime if report.market_summary else None
    metrics[1].metric("市场状态 · SPY", _REGIMES.get(regime, "未记录"))
    metrics[2].metric("交易计划", len(report.trade_plan_summary))
    metrics[3].metric(
        "待审草稿",
        sum(
            d.status is OrderDraftStatus.PENDING_REVIEW
            for d in report.order_draft_summary
        ),
    )
    st.divider()
    st.subheader("本日结论")
    st.text(report.final_recommendation or "未记录")
    if rows:
        prices = (
            pd.DataFrame(rows)
            .pivot(index="trade_date", columns="symbol", values="close")
            .dropna()
        )
        if len(prices) > 1:
            st.subheader("基准走势")
            st.caption("同期首日 = 100")
            st.line_chart(
                prices.div(prices.iloc[0]).mul(100),
                height=215,
                color=["#147A6C", "#A76832", "#375E83"][: len(prices.columns)],
                x_label="交易日",
                y_label="基准指数",
            )
    left, right = st.columns(2)
    with left:
        st.subheader("市场与组合")
        if report.market_summary:
            _text_list(report.market_summary.key_points)
        if report.portfolio_summary:
            _table(
                report.portfolio_summary.key_positions,
                {
                    "account_id": "账户",
                    "symbol": "标的",
                    "market_value": "市值（USD）",
                },
                empty="无已记录重点持仓",
            )
    with right:
        st.subheader("风险与数据缺口")
        _text_list(risk.key_risks if risk else ["未记录风险快照"])
    st.subheader("本日计划与草稿")
    a, b = st.tabs(["交易计划", "订单草稿"])
    with a:
        _table(
            [p.model_dump() for p in report.trade_plan_summary],
            {
                "symbol": "标的",
                "account_id": "账户",
                "action": "行动",
                "confidence": "置信度",
                "status": "状态",
            },
        )
    with b:
        _table(
            [d.model_dump() for d in report.order_draft_summary],
            {
                "symbol": "标的",
                "account_id": "账户",
                "status": "状态",
                "draft_id": "草稿编号",
            },
        )
    if report.journal_reminders:
        st.subheader("日志提醒")
        _text_list(report.journal_reminders)


def portfolio(data: DashboardData) -> None:
    _heading("组合持仓", "账户")
    left, right = st.columns([1, 2])
    with left:
        day = _day(data, "portfolio")
    if day is None:
        return
    with right:
        account = _account(data, "portfolio")
    view = data.read(lambda q: q.portfolio(day, account))
    metrics = st.columns(3)
    selected = next((r for r in view.risk if r["account_id"] == account), {})
    metrics[0].metric("快照净值", _money(selected.get("total_market_value")))
    metrics[1].metric(
        "持仓标的", sum((p["quantity"] or 0) != 0 for p in view.positions)
    )
    metrics[2].metric("现金快照", len(view.cash))
    st.subheader("持仓快照")
    _table(
        view.positions,
        {
            "account_id": "账户",
            "symbol": "标的",
            "quantity": "股数",
            "market_price": "市价",
            "market_value": "市值",
            "cost_basis": "成本",
            "unrealized_pnl": "未实现损益",
            "observed_at": "观察时间",
            "source": "来源",
        },
        empty="该日无持仓记录",
    )
    st.subheader("现金与风险")
    a, b = st.tabs(["现金", "风险快照"])
    with a:
        _table(
            view.cash,
            {
                "account_id": "账户",
                "currency": "币种",
                "cash_balance": "现金余额",
                "available_to_trade": "可交易现金",
                "observed_at": "观察时间",
            },
            empty="该日无现金记录",
        )
    with b:
        _table(
            view.risk,
            {
                "account_id": "账户（空白为合计）",
                "total_market_value": "净值",
                "portfolio_risk_score": "风险评分",
                "notes": "备注",
            },
            empty="该日无风险快照",
        )


def plans(data: DashboardData) -> None:
    _heading("交易计划", "策略")
    left, right = st.columns([1, 2])
    with left:
        day = _day(data, "plans")
    if day is None:
        return
    with right:
        account = _account(data, "plans")
    history = st.toggle("包含被替代计划", key="plan_history")
    records = data.read(lambda q: q.plans(day, account, history=history))
    _table(
        records,
        {
            "symbol": "标的",
            "account_id": "账户",
            "action": "行动",
            "status": "状态",
            "strategy_type": "策略",
            "confidence": "置信度",
            "reason": "依据",
        },
    )
    if not records:
        return
    names = {
        r[
            "plan_id"
        ]: f"{r['symbol']} · {r['account_id']} · {_ACTIONS.get(r['action'], r['action'])} · {r['plan_id'][-7:]}"
        for r in records
    }
    chosen = st.selectbox("计划详情", tuple(names), format_func=names.__getitem__)
    plan = data.read(lambda q: q.plan(chosen))
    if plan is None:
        return
    st.caption(plan.plan_id)
    if plan.reason:
        st.text(plan.reason)
    cols = st.columns(3)
    cols[0].metric(
        "参考限价", _money(plan.entry_order.price if plan.entry_order else None)
    )
    cols[1].metric(
        "计划股数", _number(plan.position_size.quantity if plan.position_size else None)
    )
    cols[2].metric("目标价", _money(plan.target_price_1))
    for heading, items in (
        ("入场条件", plan.entry_condition),
        ("失效条件", plan.invalid_condition),
        ("退出触发", plan.exit_trigger),
    ):
        if items:
            st.subheader(heading)
            _text_list(items)


def drafts(data: DashboardData) -> None:
    _heading("订单草稿", "审阅")
    if message := st.session_state.pop("last_review_notice", None):
        st.success(message)
    col1, col2, col3 = st.columns(3)
    with col1:
        day = _day(data, "drafts", include_all=True)
    with col2:
        account = _account(data, "drafts")
    with col3:
        status = st.selectbox(
            "状态",
            [
                OrderDraftStatus.PENDING_REVIEW,
                None,
                *(
                    state
                    for state in OrderDraftStatus
                    if state is not OrderDraftStatus.PENDING_REVIEW
                ),
            ],
            format_func=lambda state: (
                _STATUS.get(state, state) if state else "全部状态"
            ),
        )
    records = data.read(lambda q: q.drafts(day, account, status))
    _table(records, _DRAFT_COLUMNS, empty="暂无符合条件的草稿")
    if not records:
        return
    names = {
        r[
            "draft_id"
        ]: f"{r['symbol']} · {r['instruction']} · {r['account_id']} · {r['draft_id'][-7:]}"
        for r in records
    }
    chosen = st.selectbox("草稿详情", tuple(names), format_func=names.__getitem__)
    plan_id = next(item["plan_id"] for item in records if item["draft_id"] == chosen)
    draft, history, plan = data.read(
        lambda q: (
            q.draft(chosen, data.config_dir),
            q.approval_history(chosen),
            q.plan(plan_id),
        )
    )
    if draft is None:
        return
    st.divider()
    st.subheader(f"{draft.symbol} · {draft.instruction.value}")
    _snapshot(draft)
    if plan and plan.reason:
        st.caption(f"关联计划 · {_ACTIONS.get(plan.action, plan.action)}")
        st.text(plan.reason)
    if (
        draft.broker_order_id is None
        and draft.status is OrderDraftStatus.PENDING_REVIEW
    ):
        a, b, c = st.columns(3)
        if a.button("批准草稿", type="primary", icon=":material/check_circle:"):
            _confirm(data, draft, Decision.APPROVED)
        if b.button("拒绝", icon=":material/block:"):
            _confirm(data, draft, Decision.REJECTED)
        if c.button("延期", icon=":material/schedule:"):
            _confirm(data, draft, Decision.DEFERRED)
    elif draft.broker_order_id is None and draft.status is OrderDraftStatus.DEFERRED:
        a, b = st.columns(2)
        if a.button("重新待审", icon=":material/replay:"):
            _confirm(data, draft, None)
        if b.button("拒绝", icon=":material/block:"):
            _confirm(data, draft, Decision.REJECTED)
    st.subheader("审批历史")
    _table(
        history,
        {
            "decision": "决定",
            "decision_note": "备注",
            "decided_at": "决定时间",
            "approval_id": "审批编号",
        },
    )


def _order_price(value: Decimal | None) -> str:
    return "未记录" if value is None else "$" + format(value.normalize(), "f")


def _snapshot(draft: OrderDraft) -> None:
    snap = draft.order_snapshot()
    st.caption(
        f"{snap.account_id} / {snap.broker} · {_STATUS.get(draft.status, draft.status)}"
    )
    cols = st.columns(3)
    cols[0].metric("股数", format(snap.quantity.normalize(), "f"))
    cols[1].metric("限价", _order_price(snap.limit_price))
    cols[2].metric(
        "估算金额",
        _money(snap.limit_price * snap.quantity if snap.limit_price else None),
    )
    st.text(f"{snap.order_type} / {snap.time_in_force} / {snap.session}")
    if snap.stop_price is not None:
        st.text(
            f"触发价 {_order_price(snap.stop_price)} · 止损限价 {_order_price(snap.stop_limit_price)}"
        )
    st.caption(f"草稿 {draft.draft_id} · 计划 {draft.plan_id}")


@st.dialog("确认本地决定")
def _confirm(data: DashboardData, draft: OrderDraft, decision: Decision | None) -> None:
    labels = {
        Decision.APPROVED: "批准草稿",
        Decision.REJECTED: "拒绝草稿",
        Decision.DEFERRED: "延期审阅",
        None: "重新待审",
    }
    st.subheader(f"{labels[decision]} · {draft.symbol} {draft.instruction}")
    _snapshot(draft)
    with st.form(f"review-{draft.draft_id}-{draft.updated_at}-{decision}"):
        note = (
            st.text_area("审批备注（可选）", max_chars=1000)
            if decision is not None
            else ""
        )
        confirmed = (
            st.checkbox("已核对上方完整订单参数")
            if decision is Decision.APPROVED
            else True
        )
        submitted = st.form_submit_button(f"确认{labels[decision]}", type="primary")
    if not submitted:
        return
    if not confirmed:
        st.warning("请先核对并确认订单参数。")
        return
    try:
        data.review(draft, decision, note)
    except DraftError as exc:
        st.error(str(exc))
    except (DuckDBError, OSError, ValueError, KeyError, YAMLError):
        st.error("决定未保存。请检查数据库及本地配置。")
    else:
        st.session_state["last_review_notice"] = (
            f"{draft.symbol} · {labels[decision]}已保存"
        )
        st.rerun()


def journal(data: DashboardData) -> None:
    _heading("投资日志", "记录")
    dates, accounts = st.columns([1, 2])
    with dates:
        day = _day(data, "journal")
    if day is None:
        return
    with accounts:
        account = _account(data, "journal")
    records = data.read(lambda q: q.journal(day, account))
    types = sorted({r["entry_type"] for r in records if r["entry_type"]})
    kind = st.selectbox(
        "记录类型",
        [None, *types],
        format_func=lambda t: _ENTRY_TYPES.get(t, t) if t else "全部类型",
    )
    _table(
        [r for r in records if kind is None or r["entry_type"] == kind],
        {
            "entry_type": "类型",
            "symbol": "标的",
            "account_id": "账户",
            "action": "行动",
            "decision_reason": "决策依据",
            "user_note": "人工备注",
            "system_note": "系统记录",
            "created_at": "入库时间",
            "journal_id": "日志编号",
        },
    )


def performance(data: DashboardData) -> None:
    _heading("绩效复盘", "复盘")
    account = _account(data, "performance")
    records, outcomes = data.read(
        lambda q: (q.performance(account), q.outcomes(account))
    )
    a, b = st.tabs(["周期复盘", "计划与成交结果"])
    with a:
        if records:
            ids = {r["review_id"]: r for r in records}

            def period(key):
                item = ids[key]
                label = _REPORTS.get(item["review_type"], item["review_type"])
                return f"{item['period_start']} 至 {item['period_end']} · {label} · {item['account_id'] or '组合'}"

            item = ids[st.selectbox("复盘期间", tuple(ids), format_func=period)]
            metrics = st.columns(4)
            metrics[0].metric("计划", item["plan_count"])
            metrics[1].metric("成交", item["trade_count"])
            metrics[2].metric("胜率", _pct(item["win_rate"]))
            metrics[3].metric("平均收益", _pct(item["average_return"]))
            for label, field in (
                ("摘要", "summary"),
                ("经验", "lessons"),
                ("下一步", "next_actions"),
            ):
                if item[field]:
                    st.subheader(label)
                    st.text(item[field])
        else:
            st.info("暂无已入库的周期复盘。")
    with b:
        basis = st.segmented_control(
            "样本口径", ["全部", "计划", "成交"], default="全部"
        )
        _table(
            [
                {
                    **item,
                    **{
                        f"outcome_return_{days}d": _pct(item[f"outcome_return_{days}d"])
                        for days in (5, 20, 60)
                    },
                }
                for item in outcomes
                if basis in (None, "全部", item["basis"])
            ],
            {
                "symbol": "标的",
                "account_id": "账户",
                "reference_date": "参考日",
                "basis": "口径",
                "outcome_return_5d": "5 日收益",
                "outcome_return_20d": "20 日收益",
                "outcome_return_60d": "60 日收益",
                "outcome_label": "结果",
                "lesson": "备注",
            },
        )


def settings(data: DashboardData) -> None:
    _heading("设置", "本地配置")
    app = read_config(data.config_dir, "app")["app"]
    risk = read_config(data.config_dir, "risk")["risk"]
    brokers = read_config(data.config_dir, "broker")["brokers"]
    cols = st.columns(3)
    cols[0].metric("业务时区", "America/Chicago")
    cols[1].metric("基准币种", app["base_currency"])
    cols[2].metric("订单提交", "关闭")
    st.subheader("券商能力")
    _table(
        [
            {
                "broker": key.upper(),
                "mode": row.get("mode"),
                "enabled": row.get("enabled"),
                "drafts": row.get("order_draft_enabled"),
                "submission": False,
            }
            for key, row in brokers.items()
        ],
        {
            "broker": "券商",
            "mode": "模式",
            "enabled": "启用",
            "drafts": "支持草稿",
            "submission": "本地提交",
        },
    )
    st.subheader("账户权限")
    if data.path.is_file():
        _table(
            data.read(lambda q: q.accounts()),
            {
                "account_id": "账户",
                "broker": "券商",
                "account_role": "角色",
                "individual_stock_policy": "个股策略",
                "base_currency": "币种",
                "order_draft_enabled": "允许草稿",
                "csv_import_enabled": "允许导入",
                "is_active": "启用",
            },
        )
    else:
        st.caption("数据库未初始化")
    st.subheader("风控参数")
    fields = (
        ("max_single_stock_weight", "单账户个股上限"),
        ("max_new_trade_weight", "单笔新增仓位上限"),
        ("max_combined_symbol_weight", "组合单标的上限"),
        ("max_combined_sector_weight", "组合板块上限"),
        ("max_trade_risk_percent", "单笔风险上限"),
    )
    _table(
        [{"name": label, "value": _pct(risk.get(key))} for key, label in fields]
        + [
            {
                "name": "入场置信度门槛",
                "value": _number(risk.get("min_entry_confidence_for_order_draft")),
            },
            {
                "name": "小时确认最长有效时间（分钟）",
                "value": _number(risk.get("max_hourly_age_minutes")),
            },
        ],
        {"name": "参数", "value": "当前值"},
    )
