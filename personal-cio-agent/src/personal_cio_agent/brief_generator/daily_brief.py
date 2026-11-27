from datetime import date
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shared.enums import Action, OrderDraftStatus, TradePlanStatus
from shared.models import DailyCioBrief
from shared.models.brief import (
    MarketSummary,
    OrderDraftSummary,
    PortfolioSummary,
    RiskSummary,
    TradePlanSummary,
)

_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
_ENVIRONMENT = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

_REVIEWABLE = {
    TradePlanStatus.DRAFT,
    TradePlanStatus.REVIEWED,
    TradePlanStatus.APPROVED,
}
_ACTIVE = {Action.ADD, Action.RE_ENTRY, Action.REDUCE, Action.EXIT, Action.EXIT_ONLY}


def _text(value: str) -> str:
    return " ".join(str(value).splitlines()).translate(
        str.maketrans({char: "\\" + char for char in "\\|`[]*_!~"})
    )


def _money(value: Decimal | str | None) -> str:
    return "待补齐" if value is None else f"${Decimal(value):,.2f}"


_ENVIRONMENT.filters.update(md_text=_text, money=_money)


def brief_id_for(day: date) -> str:
    return f"BRIEF-{day:%Y%m%d}"


def build_daily_brief(
    day: date,
    *,
    market: MarketSummary,
    portfolio: PortfolioSummary,
    risk: RiskSummary,
    plans: list[TradePlanSummary],
    drafts: list[OrderDraftSummary],
    reminders: list[str],
) -> DailyCioBrief:
    return DailyCioBrief(
        brief_id=brief_id_for(day),
        brief_date=day,
        market_summary=market,
        portfolio_summary=portfolio,
        risk_summary=risk,
        trade_plan_summary=plans,
        order_draft_summary=drafts,
        journal_reminders=reminders,
        final_recommendation=_recommendation(market, portfolio, plans, drafts),
    )


def _recommendation(
    market: MarketSummary,
    portfolio: PortfolioSummary,
    plans: list[TradePlanSummary],
    drafts: list[OrderDraftSummary],
) -> str:
    if any(
        draft.status in (OrderDraftStatus.SUBMITTING, OrderDraftStatus.UNKNOWN)
        for draft in drafts
    ):
        return "优先核对状态未确认的订单记录。"
    plan_links = {plan.plan_id: (plan.account_id, plan.symbol) for plan in plans}
    if any(
        plan_links.get(draft.plan_id) != (draft.account_id, draft.symbol)
        for draft in drafts
    ):
        return "订单草稿与计划的账户或标的关联不一致，请先复核来源。"
    if market.market_regime is None or portfolio.total_value is None:
        return "先补齐当日市场或组合数据，再复核交易计划和订单草稿。"
    if market.market_regime == "HIGH_RISK":
        return "SPY 当日信号提示高风险，先复核风险和已有计划。"

    reviewable = [plan for plan in plans if plan.status in _REVIEWABLE]
    active_plan_ids = {
        plan.plan_id
        for plan in reviewable
        if plan.action in _ACTIVE - {Action.EXIT_ONLY}
    }
    pending = sum(
        draft.plan_id in active_plan_ids
        and draft.status is OrderDraftStatus.PENDING_REVIEW
        for draft in drafts
    )
    if pending:
        return f"有 {pending} 张待审草稿，请核对账户、仓位和订单条件后再决定。"
    if any(plan.action in _ACTIVE for plan in reviewable):
        return "有可复核的交易计划，请检查触发条件和失效条件。"
    if any(plan.action is Action.WATCH for plan in reviewable):
        return "继续观察，等待计划条件满足后复核。"
    return "今日暂无待审计划，按原有安排跟踪市场与持仓。"


def render_markdown(brief: DailyCioBrief) -> str:
    return _ENVIRONMENT.get_template("daily_cio_brief.md.j2").render(brief=brief)
