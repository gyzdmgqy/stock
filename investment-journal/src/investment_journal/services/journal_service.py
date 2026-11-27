from contextlib import nullcontext
from zoneinfo import ZoneInfo

from duckdb import DuckDBPyConnection

from shared.enums import ApprovalDecision as ApprovalDecisionType
from shared.enums import JournalEntryType
from shared.models import (
    ApprovalDecision,
    BrokerTransaction,
    DailyCioBrief,
    DailySignal,
    JournalEntry,
    OrderDraft,
    TradePlan,
)

from ..repositories.journal_repository import (
    JournalRepository,
    journal_key,
    outcome_key,
)

APP_TIMEZONE = ZoneInfo("America/Chicago")


def approval_note(decision: ApprovalDecisionType) -> str:
    return f"审批结果 {decision.value}"


def _plan_fields(plan: TradePlan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "symbol": plan.symbol,
        "account_id": plan.account_id,
        "action": plan.action,
        "strategy_type": plan.strategy_type,
        "confidence": plan.confidence,
    }


def _merged_id(label: str, *values: str | None) -> str | None:
    ids = {value for value in values if value is not None}
    if len(ids) > 1:
        raise ValueError(f"{label}关联冲突")
    return next(iter(ids)) if ids else None


class JournalService:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._repository = JournalRepository(db)

    def record_plan(self, plan: TradePlan) -> JournalEntry:
        plan = self._repository.require_plan(plan.plan_id)
        return self._repository.record_entry(
            JournalEntry(
                journal_id=journal_key("PLAN", plan.plan_id),
                journal_date=plan.plan_date,
                entry_type=JournalEntryType.TRADE_PLAN_REVIEW,
                thesis=plan.thesis,
                decision_reason=plan.reason,
                **_plan_fields(plan),
            ),
            outcome_id=outcome_key("PLAN", plan.plan_id),
        )

    def record_signal(self, signal: DailySignal) -> JournalEntry:
        return self._repository.record_entry(
            JournalEntry(
                journal_id=journal_key("SIGNAL", signal.signal_id),
                journal_date=signal.trade_date,
                entry_type=JournalEntryType.SIGNAL_REVIEW,
                symbol=signal.symbol,
                action=signal.action_hint,
                market_regime=signal.market_regime,
                confidence=signal.confidence,
                system_note=signal.reason,
            )
        )

    def record_draft(self, draft: OrderDraft) -> JournalEntry:
        persisted = self._repository.require_draft(draft.draft_id)
        if (
            persisted.plan_id != draft.plan_id
            or persisted.order_snapshot() != draft.order_snapshot()
        ):
            raise ValueError("草稿与已入库的订单快照不一致")
        plan = self._repository.require_plan(draft.plan_id)
        draft_date = (
            persisted.created_at.astimezone(APP_TIMEZONE).date()
            if persisted.created_at
            else plan.plan_date
        )
        return self._repository.record_entry(
            JournalEntry(
                journal_id=journal_key("DRAFT", draft.draft_id),
                journal_date=draft_date,
                entry_type=JournalEntryType.ORDER_REVIEW,
                draft_id=draft.draft_id,
                system_note=f"订单草稿 {draft.instruction.value} {draft.quantity} 股。",
                **_plan_fields(plan),
            )
        )

    def record_approval(self, approval: ApprovalDecision) -> JournalEntry:
        approval = ApprovalDecision.model_validate(approval.model_dump())
        draft = self._repository.require_draft(approval.draft_id)
        if draft.plan_id != approval.plan_id:
            raise ValueError("审批与草稿所属的计划不一致")
        if (
            approval.decision is ApprovalDecisionType.APPROVED
            and approval.approved_payload != draft.order_snapshot()
        ):
            raise ValueError("审批快照与原草稿不一致")
        plan = self._repository.require_plan(approval.plan_id)
        return self._repository.record_entry(
            JournalEntry(
                journal_id=journal_key("APPROVAL", approval.approval_id),
                journal_date=approval.decided_at.astimezone(APP_TIMEZONE).date(),
                entry_type=JournalEntryType.ORDER_REVIEW,
                draft_id=draft.draft_id,
                decision_reason=approval.decision_note,
                system_note=approval_note(approval.decision),
                **_plan_fields(plan),
            )
        )

    def record_transaction(
        self,
        transaction: BrokerTransaction,
        *,
        plan_id: str | None = None,
        in_transaction: bool = False,
    ) -> JournalEntry:
        # CSV 导入方持有批次事务，成交和日志必须一起提交。
        with nullcontext() if in_transaction else self._repository.transaction():
            stored = self._repository.require_transaction(transaction.transaction_id)
            if (transaction.broker, transaction.account_id, transaction.symbol) != (
                stored.broker,
                stored.account_id,
                stored.symbol,
            ):
                raise ValueError("券商记录的账户或标的不一致")
            draft_id = _merged_id("草稿", stored.draft_id, transaction.draft_id)
            draft = self._repository.require_draft(draft_id) if draft_id else None
            if draft and (draft.account_id, draft.symbol, draft.broker) != (
                stored.account_id,
                stored.symbol,
                stored.broker,
            ):
                raise ValueError("成交与订单草稿的账户、券商或标的不一致")
            resolved_plan_id = _merged_id(
                "计划",
                stored.plan_id,
                transaction.plan_id,
                plan_id,
                draft.plan_id if draft else None,
            )
            plan = (
                self._repository.require_plan(resolved_plan_id)
                if resolved_plan_id
                else None
            )
            if plan and (plan.account_id, plan.symbol) != (
                stored.account_id,
                stored.symbol,
            ):
                raise ValueError("成交与交易计划的账户或标的不一致")

            day = stored.trade_date
            if day is None and stored.transaction_time is not None:
                day = stored.transaction_time.astimezone(APP_TIMEZONE).date()
            if day is None:
                raise ValueError("券商记录缺少交易日期和时间")
            if (stored.plan_id, stored.draft_id) != (resolved_plan_id, draft_id):
                self._repository.link_transaction(
                    stored.transaction_id, resolved_plan_id, draft_id
                )

            return self._repository.record_entry(
                JournalEntry(
                    journal_id=journal_key("TRANSACTION", stored.transaction_id),
                    journal_date=day,
                    entry_type=JournalEntryType.TRADE_EXECUTION,
                    plan_id=resolved_plan_id,
                    draft_id=draft_id,
                    transaction_id=stored.transaction_id,
                    account_id=stored.account_id,
                    symbol=stored.symbol,
                    action=plan.action if plan else None,
                    strategy_type=plan.strategy_type if plan else None,
                    confidence=plan.confidence if plan else None,
                    system_note=f"券商记录 {stored.transaction_type.value}。",
                ),
                outcome_id=outcome_key("TRANSACTION", stored.transaction_id),
                enrich_links=True,
            )

    def record_brief(self, brief: DailyCioBrief) -> JournalEntry:
        market = brief.market_summary
        return self._repository.record_entry(
            JournalEntry(
                journal_id=journal_key("BRIEF", brief.brief_id),
                journal_date=brief.brief_date,
                entry_type=JournalEntryType.DAILY,
                market_regime=market.market_regime if market else None,
                confidence=market.confidence if market else None,
                decision_reason=brief.final_recommendation,
                system_note=f"每日 CIO 简报 {brief.brief_id}。",
            )
        )
