import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from duckdb import DuckDBPyConnection

from investment_journal.services.journal_service import JournalService
from shared.db import insert_journal_entry
from shared.enums import (
    ErrorType,
    JournalEntryType,
    OrderInstruction,
    TransactionSource,
    TransactionType,
)
from shared.enums import OrderDraftStatus as Status
from shared.models import (
    ApprovalDecision,
    BrokerTransaction,
    JournalEntry,
    OrderDraft,
    OrderSnapshot,
)
from trade_planner.rules.hourly_gate import APP_TIMEZONE

from ..drafts import DraftError, OrderDraftService
from .simulator import SimulatedFill, SimulationRequest

_EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SubmissionAttempt:
    request: SimulationRequest
    plan_id: str
    approval_id: str
    status: Status
    broker_order_id: str | None
    event_number: int
    started_at: datetime
    updated_at: datetime


class SubmissionRepository:
    def __init__(self, db: DuckDBPyConnection, gateway: OrderDraftService) -> None:
        self.db = db
        self.gateway = gateway

    def require_simulation_database(self) -> None:
        row = self.db.execute(
            "SELECT path FROM duckdb_databases() WHERE database_name = current_database()"
        ).fetchone()
        if (
            not row
            or row[0] is None
            or not Path(row[0]).resolve().name.endswith(".simulation.duckdb")
        ):
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED,
                "只允许在独立的 .simulation.duckdb 模拟数据库中运行。",
            )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.require_simulation_database()
        self.db.begin()
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def get(self, draft_id: str) -> SubmissionAttempt | None:
        row = self.db.execute(
            """
            SELECT attempt_id, plan_id, approval_id, order_payload, status, broker_order_id,
                event_number, started_at, updated_at
            FROM order_submission_attempt WHERE draft_id = ? AND mode = 'SIMULATED'
            """,
            [draft_id],
        ).fetchone()
        if row is None:
            return None
        (
            attempt_id,
            plan_id,
            approval_id,
            payload,
            status,
            broker_id,
            revision,
            started,
            updated,
        ) = row
        request = SimulationRequest(
            attempt_id=attempt_id,
            draft_id=draft_id,
            order=OrderSnapshot.model_validate_json(payload),
        )
        return SubmissionAttempt(
            request,
            plan_id,
            approval_id,
            Status(status),
            broker_id,
            revision,
            started,
            updated,
        )

    def reserve(
        self, draft: OrderDraft, approved: ApprovalDecision, now: datetime
    ) -> SubmissionAttempt:
        if self.db.execute(
            "SELECT 1 FROM order_submission_attempt WHERE draft_id = ? OR plan_id = ?",
            [draft.draft_id, draft.plan_id],
        ).fetchone():
            raise DraftError(
                ErrorType.DUPLICATE_ORDER, "此草稿或计划已提交过，不可重发。"
            )
        new = draft.transition_to(Status.SUBMITTING, approval=approved)
        request = SimulationRequest(
            attempt_id=f"SIM-ATT-{uuid4().hex}",
            draft_id=draft.draft_id,
            order=draft.order_snapshot(),
        )
        self.db.execute(
            """
            INSERT INTO order_submission_attempt (
                attempt_id, draft_id, plan_id, account_id, approval_id, mode, order_payload,
                status, event_number, started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'SIMULATED', ?, 'SUBMITTING', 1, ?, ?)
            """,
            [
                request.attempt_id,
                draft.draft_id,
                draft.plan_id,
                draft.account_id,
                approved.approval_id,
                request.order.model_dump_json(),
                now,
                now,
            ],
        )
        self._update_draft(draft, new.status, None, now)
        attempt = SubmissionAttempt(
            request, draft.plan_id, approved.approval_id, new.status, None, 1, now, now
        )
        self._event(attempt, None)
        return attempt

    def advance(
        self,
        attempt: SubmissionAttempt,
        status: Status,
        now: datetime,
        *,
        broker_order_id: str | None = None,
        response: dict | None = None,
    ) -> SubmissionAttempt:
        draft = self.gateway.get_draft(attempt.request.draft_id)
        if (
            draft is None
            or draft.status is not attempt.status
            or draft.plan_id != attempt.plan_id
            or draft.order_snapshot() != attempt.request.order
            or draft.updated_at != attempt.updated_at
            or draft.broker_order_id != attempt.broker_order_id
            or now < attempt.updated_at
        ):
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "草稿与原提交证据不一致或状态已变更。"
            )
        if status is not draft.status and not draft.status.allows(status):
            raise DraftError(
                ErrorType.VALIDATION_ERROR, f"草稿不能从 {draft.status} 转为 {status}。"
            )
        if broker_order_id is not None and attempt.broker_order_id not in (
            None,
            broker_order_id,
        ):
            raise DraftError(
                ErrorType.VALIDATION_ERROR, "对账响应的券商订单 ID 与原证据不一致。"
            )
        if (
            broker_order_id is not None
            and self.db.execute(
                "SELECT 1 FROM order_submission_attempt WHERE account_id = ? AND broker_order_id = ? AND attempt_id <> ?",
                [draft.account_id, broker_order_id, attempt.request.attempt_id],
            ).fetchone()
        ):
            raise DraftError(
                ErrorType.DUPLICATE_ORDER, "此券商订单 ID 已关联另一模拟提交尝试。"
            )
        linked_id = broker_order_id or attempt.broker_order_id
        new = replace(
            attempt,
            status=status,
            broker_order_id=linked_id,
            event_number=attempt.event_number + 1,
            updated_at=now,
        )
        updated = self.db.execute(
            """
            UPDATE order_submission_attempt SET status = ?, broker_order_id = ?, updated_at = ?, event_number = ?
            WHERE attempt_id = ? AND event_number = ? RETURNING attempt_id
            """,
            [
                status.value,
                linked_id,
                now,
                new.event_number,
                attempt.request.attempt_id,
                attempt.event_number,
            ],
        ).fetchone()
        if updated is None:
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "提交尝试已变更，请重新对账。"
            )
        self._update_draft(draft, status, linked_id, now)
        self._event(new, response)
        return new

    def _update_draft(
        self, draft: OrderDraft, status: Status, broker_id: str | None, now: datetime
    ) -> None:
        row = self.db.execute(
            """
            UPDATE order_draft SET status = ?, broker_order_id = ?, updated_at = ?
            WHERE draft_id = ? AND status = ? AND updated_at IS NOT DISTINCT FROM ?
            RETURNING draft_id
            """,
            [
                status.value,
                broker_id,
                now,
                draft.draft_id,
                draft.status.value,
                draft.updated_at,
            ],
        ).fetchone()
        if row is None:
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "草稿状态已变更，请重新审阅。"
            )

    def _event(self, attempt: SubmissionAttempt, response: dict | None) -> None:
        request = attempt.request
        self.db.execute(
            "INSERT INTO order_submission_event VALUES (?, ?, ?, ?, ?)",
            [
                request.attempt_id,
                attempt.event_number,
                attempt.status.value,
                attempt.updated_at,
                (
                    json.dumps(response, ensure_ascii=False, allow_nan=False)
                    if response is not None
                    else None
                ),
            ],
        )
        insert_journal_entry(
            self.db,
            JournalEntry(
                journal_id=f"JRN-{request.attempt_id}-{attempt.event_number}",
                journal_date=attempt.updated_at.astimezone(APP_TIMEZONE).date(),
                entry_type=JournalEntryType.ORDER_REVIEW,
                draft_id=request.draft_id,
                plan_id=attempt.plan_id,
                symbol=request.order.symbol,
                account_id=request.order.account_id,
                system_note=f"模拟提交状态：{attempt.status.value}。",
                created_at=attempt.updated_at,
            ),
        )

    def record_fill(
        self,
        attempt: SubmissionAttempt,
        fill: SimulatedFill,
        broker_id: str,
        now: datetime,
    ) -> None:
        order = attempt.request.order
        if not attempt.started_at <= fill.executed_at <= now:
            raise DraftError(
                ErrorType.VALIDATION_ERROR, "模拟成交时刻不在该次提交的有效时间内。"
            )
        buy = order.instruction is OrderInstruction.BUY
        if order.limit_price is not None and (
            (buy and fill.price > order.limit_price)
            or (not buy and fill.price < order.limit_price)
        ):
            raise DraftError(ErrorType.VALIDATION_ERROR, "模拟成交价超出已批准限价。")
        key = sha256(
            f"{attempt.request.attempt_id}:{fill.fill_id}".encode()
        ).hexdigest()
        identifier = f"SIM-FILL-{key}"
        existing = self.db.execute(
            "SELECT quantity, price, transaction_time, broker_order_id FROM broker_transaction WHERE transaction_id = ?",
            [identifier],
        ).fetchone()
        if existing is not None:
            if existing != (fill.quantity, fill.price, fill.executed_at, broker_id):
                raise DraftError(
                    ErrorType.VALIDATION_ERROR, "同一模拟成交 ID 对应不同的成交数据。"
                )
            return
        item = BrokerTransaction(
            transaction_id=identifier,
            broker=order.broker,
            account_id=order.account_id,
            symbol=order.symbol,
            transaction_type=TransactionType.BUY if buy else TransactionType.SELL,
            transaction_time=fill.executed_at,
            trade_date=fill.executed_at.astimezone(_EASTERN).date(),
            quantity=fill.quantity,
            price=fill.price,
            order_type=order.order_type,
            broker_order_id=broker_id,
            broker_transaction_id=identifier,
            plan_id=attempt.plan_id,
            draft_id=attempt.request.draft_id,
            source=TransactionSource.MANUAL,
            deduplication_key=identifier,
            note="模拟成交，不是真实券商记录。",
            created_at=now,
        )
        fields = item.model_dump(mode="json")
        self.db.execute(
            f"INSERT INTO broker_transaction ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            list(fields.values()),
        )
        JournalService(self.db).record_transaction(item, in_transaction=True)
