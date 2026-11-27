import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import yaml
from duckdb import DuckDBPyConnection
from pydantic import BaseModel, ValidationError

from investment_journal.services.journal_service import JournalService
from shared.db import get_trade_plan
from shared.db.database import DEFAULT_CONFIG_DIR
from shared.enums import ApprovalDecision as Decision
from shared.enums import ErrorType, OrderDraftStatus
from shared.models import ApprovalDecision, OrderDraft, OrderSnapshot, TradePlan
from trade_planner.planners.base import RiskLimits

from .duplicate_detector import require_no_duplicate
from .order_draft_validator import DraftError, OrderDraftValidator

_DRAFT_COLUMNS = tuple(OrderDraft.model_fields)
_APPROVAL_COLUMNS = tuple(ApprovalDecision.model_fields)
_JSON_COLUMNS = {"raw_payload", "approved_payload"}


@dataclass(frozen=True)
class ReviewResult:
    approval: ApprovalDecision
    draft: OrderDraft
    replacement: OrderDraft | None = None


class OrderDraftService:
    """本地草稿与审批入口，不包含券商执行能力。"""

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
        self._validator = OrderDraftValidator(
            db, RiskLimits.model_validate(limits.model_dump())
        )

    def create_draft(
        self, plan_id: str, *, as_of: datetime | None = None
    ) -> OrderDraft:
        now = _evaluation_time(as_of)
        with self._transaction():
            plan = self._require_plan(plan_id)
            snapshot = self._validator.baseline(plan, now)
            self._validator.validate(plan, snapshot, snapshot, now)
            draft = self._new_draft(plan_id, snapshot, now, initial=True)
            require_no_duplicate(self._db, draft)
            self._insert("order_draft", draft)
        return draft

    def record_decision(
        self,
        draft_id: str,
        decision: Decision,
        *,
        reviewed_payload: OrderSnapshot | None = None,
        decision_note: str | None = None,
        replacement: OrderSnapshot | None = None,
        as_of: datetime | None = None,
        expected_draft: OrderDraft | None = None,
    ) -> ReviewResult:
        now = _evaluation_time(as_of)
        with self._transaction():
            draft = self._require_draft(draft_id, now)
            _require_unchanged(draft, expected_draft)
            decision = Decision(decision)
            if (replacement is not None) != (decision is Decision.MODIFIED):
                raise DraftError(
                    ErrorType.VALIDATION_ERROR, "修改决策必须提供新的订单参数。"
                )
            if decision is Decision.APPROVED and reviewed_payload is None:
                raise DraftError(
                    ErrorType.USER_APPROVAL_REQUIRED,
                    "批准必须提供用户已审阅的完整订单快照。",
                )
            approval = ApprovalDecision(
                approval_id=f"APR-{uuid4().hex}",
                draft_id=draft_id,
                plan_id=draft.plan_id,
                decision=decision,
                decision_note=decision_note,
                approved_payload=reviewed_payload,
                decided_at=now,
            )
            new = None
            if replacement is not None:
                replacement = OrderSnapshot.model_validate(replacement.model_dump())
                if replacement == draft.order_snapshot():
                    raise DraftError(
                        ErrorType.VALIDATION_ERROR, "修改后的订单参数没有变化。"
                    )
                candidate = self._new_draft(draft.plan_id, replacement, now)
                updated, new = draft.replace_with(candidate, approval)
                self._check_current(new, now)
                require_no_duplicate(self._db, new, replacing=draft_id)
            else:
                updated = draft.transition_to(
                    OrderDraftStatus(decision.value), approval=approval
                )
                if decision is Decision.APPROVED:
                    self._check_current(updated, now, approving=True)
                    require_no_duplicate(self._db, updated, replacing=draft_id)
            updated = self._update_status(draft, updated, now)
            if new is not None:
                self._insert("order_draft", new)
            self._insert("approval_record", approval)
            JournalService(self._db).record_approval(approval)
        return ReviewResult(approval, updated, new)

    def reopen_deferred(
        self,
        draft_id: str,
        *,
        as_of: datetime | None = None,
        expected_draft: OrderDraft | None = None,
    ) -> OrderDraft:
        now = _evaluation_time(as_of)
        with self._transaction():
            draft = self._require_draft(draft_id, now)
            _require_unchanged(draft, expected_draft)
            pending = draft.transition_to(OrderDraftStatus.PENDING_REVIEW)
            self._check_current(pending, now)
            require_no_duplicate(self._db, pending, replacing=draft_id)
            return self._update_status(draft, pending, now)

    def expire_draft(
        self, draft_id: str, *, as_of: datetime | None = None
    ) -> OrderDraft:
        now = _evaluation_time(as_of)
        with self._transaction():
            draft = self._require_draft(draft_id, now)
            expired = draft.transition_to(OrderDraftStatus.EXPIRED)
            return self._update_status(draft, expired, now)

    def get_draft(self, draft_id: str) -> OrderDraft | None:
        row = self._db.execute(
            f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM order_draft WHERE draft_id = ?",
            [draft_id],
        ).fetchone()
        return OrderDraft.model_validate(_record(_DRAFT_COLUMNS, row)) if row else None

    def get_approval(self, approval_id: str) -> ApprovalDecision | None:
        row = self._db.execute(
            f"SELECT {', '.join(_APPROVAL_COLUMNS)} FROM approval_record WHERE approval_id = ?",
            [approval_id],
        ).fetchone()
        return (
            ApprovalDecision.model_validate(_record(_APPROVAL_COLUMNS, row))
            if row
            else None
        )

    def require_current_approval(
        self,
        draft_id: str,
        *,
        as_of: datetime | None = None,
        in_transaction: bool = False,
    ) -> ApprovalDecision:
        """仅核验当前本地批准，无任何提交行为。"""
        now = _evaluation_time(as_of)
        with nullcontext() if in_transaction else self._transaction():
            draft = self._require_draft(draft_id, now)
            rows = self._db.execute(
                f"SELECT {', '.join(_APPROVAL_COLUMNS)} FROM approval_record "
                "WHERE draft_id = ? ORDER BY decided_at DESC NULLS LAST, approval_id DESC LIMIT 2",
                [draft_id],
            ).fetchall()
            if draft.status is not OrderDraftStatus.APPROVED or not rows:
                raise DraftError(
                    ErrorType.USER_APPROVAL_REQUIRED, "草稿没有当前的已记录批准。"
                )
            latest = _record(_APPROVAL_COLUMNS, rows[0])
            if (
                len(rows) > 1
                and latest["decided_at"]
                == _record(_APPROVAL_COLUMNS, rows[1])["decided_at"]
            ):
                raise DraftError(
                    ErrorType.USER_APPROVAL_REQUIRED,
                    "最近审批决定的时间相同，无法确定有效批准。",
                )
            approval = ApprovalDecision.model_validate(latest)
            if (
                approval.decision is not Decision.APPROVED
                or approval.plan_id != draft.plan_id
                or approval.decided_at != draft.updated_at
                or approval.decided_at > now
                or approval.approved_payload != draft.order_snapshot()
            ):
                raise DraftError(
                    ErrorType.USER_APPROVAL_REQUIRED, "批准快照不再匹配当前草稿。"
                )
            self._check_current(draft, now, approving=True)
            require_no_duplicate(self._db, draft, replacing=draft_id)
            return approval

    def _require_plan(self, plan_id: str) -> TradePlan:
        plan = get_trade_plan(self._db, plan_id)
        if plan is None:
            raise DraftError(ErrorType.DATA_MISSING, "找不到订单草稿关联的交易计划。")
        return plan

    def _require_draft(self, draft_id: str, as_of: datetime) -> OrderDraft:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise DraftError(ErrorType.DATA_MISSING, "找不到订单草稿。")
        if draft.broker_order_id is not None:
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "已关联券商订单的草稿不能在本地更改。"
            )
        latest = draft.updated_at or draft.created_at
        if latest is not None and latest > as_of:
            raise DraftError(ErrorType.VALIDATION_ERROR, "决策时间早于草稿的最新状态。")
        return draft

    def _check_current(
        self, draft: OrderDraft, now: datetime, *, approving: bool = False
    ) -> None:
        plan = self._require_plan(draft.plan_id)
        baseline = self._validator.baseline(plan, now)
        if draft.replaces_draft_id is None and draft.order_snapshot() != baseline:
            raise DraftError(ErrorType.RISK_RULE_BLOCKED, "初始草稿参数与计划不一致。")
        self._validator.validate(
            plan, draft.order_snapshot(), baseline, now, approving=approving
        )

    @staticmethod
    def _new_draft(
        plan_id: str, snapshot: OrderSnapshot, now: datetime, *, initial: bool = False
    ) -> OrderDraft:
        # 初始草稿 ID 由计划决定，主键同时保护同一计划的重复插入。
        identity = (
            sha256(plan_id.encode("utf-8")).hexdigest()[:32] if initial else uuid4().hex
        )
        return OrderDraft(
            draft_id=f"OD-{identity}",
            plan_id=plan_id,
            created_at=now,
            **snapshot.model_dump(),
        )

    def _update_status(
        self, previous: OrderDraft, current: OrderDraft, now: datetime
    ) -> OrderDraft:
        result = self._db.execute(
            "UPDATE order_draft SET status = ?, updated_at = ? WHERE draft_id = ? AND status = ? RETURNING draft_id",
            [current.status.value, now, previous.draft_id, previous.status.value],
        ).fetchone()
        if result is None:
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "草稿状态已变更，请重新审阅。"
            )
        return OrderDraft.model_validate({**current.model_dump(), "updated_at": now})

    def _insert(self, table: str, model: BaseModel) -> None:
        fields = model.model_dump()
        values = []
        for key, value in fields.items():
            if key in _JSON_COLUMNS and value is not None:
                value = json.dumps(model.model_dump(mode="json")[key], allow_nan=False)
            elif isinstance(value, StrEnum):
                value = value.value
            values.append(value)
        self._db.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            values,
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.begin()
        try:
            yield
            self._db.commit()
        except BaseException as exc:
            self._db.rollback()
            if isinstance(exc, ValidationError):
                raise DraftError(
                    ErrorType.VALIDATION_ERROR, "订单、审批或计划证据不符合规范。"
                ) from exc
            if isinstance(exc, ValueError) and not isinstance(exc, DraftError):
                raise DraftError(ErrorType.VALIDATION_ERROR, str(exc)) from exc
            raise


def _evaluation_time(as_of: datetime | None) -> datetime:
    if as_of is None:
        return datetime.now(UTC)
    if as_of.utcoffset() is None:
        raise DraftError(ErrorType.VALIDATION_ERROR, "评估时间必须包含时区。")
    return as_of.astimezone(UTC)


def _require_unchanged(draft: OrderDraft, expected: OrderDraft | None) -> None:
    if expected is not None and expected != draft:
        raise DraftError(ErrorType.VALIDATION_ERROR, "草稿已变更，请刷新后重新审阅。")


def _record(columns: tuple[str, ...], row: tuple) -> dict:
    fields = dict(zip(columns, row, strict=True))
    for key in _JSON_COLUMNS & fields.keys():
        if fields[key] is not None:
            fields[key] = json.loads(fields[key])
    return fields
