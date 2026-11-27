from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from duckdb import DuckDBPyConnection
from pydantic import ValidationError

from shared.enums import Broker, ErrorType
from shared.enums import OrderDraftStatus as Status

from ..drafts import DraftError, OrderDraftService
from ._repository import SubmissionAttempt, SubmissionRepository
from .simulator import SimulatedReply, SimulatedSchwabAdapter

_RECOVERY_AGE = timedelta(minutes=2)
_CAN_RECONCILE = {Status.UNKNOWN, Status.SUBMITTED, Status.PARTIALLY_FILLED}
_ACCEPTED_OUTCOMES = {Status.PARTIALLY_FILLED, Status.FILLED, Status.CANCELED}


@dataclass(frozen=True)
class SubmissionPolicy:
    enabled: bool = False
    phase12_verified: bool = False

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], *, phase12_verified: bool = False
    ) -> "SubmissionPolicy":
        flag = env.get("ORDER_SUBMISSION_ENABLED", "false").strip().lower()
        if flag not in ("false", "true"):
            raise DraftError(
                ErrorType.VALIDATION_ERROR,
                "ORDER_SUBMISSION_ENABLED 必须为 true 或 false。",
            )
        return cls(enabled=flag == "true", phase12_verified=phase12_verified)

    def require_enabled(self) -> None:
        if self.enabled is not True or self.phase12_verified is not True:
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED,
                "模拟提交必须显式启用，且 Phase 12 必须已验收。",
            )


class SubmissionService:
    """只执行本地模拟。不注册真实券商提交适配器或运行入口。"""

    def __init__(
        self,
        db: DuckDBPyConnection,
        adapter: SimulatedSchwabAdapter,
        *,
        policy: SubmissionPolicy = SubmissionPolicy(),
    ) -> None:
        if type(adapter) is not SimulatedSchwabAdapter:
            raise DraftError(ErrorType.RISK_RULE_BLOCKED, "只允许使用内置模拟适配器。")
        self._db = db
        self._gateway = OrderDraftService(db)
        self._repository = SubmissionRepository(db, self._gateway)
        self._repository.require_simulation_database()
        self._adapter = adapter
        self._policy = policy

    def submit_approved_order(
        self, draft_id: str, *, as_of: datetime | None = None
    ) -> SubmissionAttempt:
        self._policy.require_enabled()
        now = _instant(as_of)
        with self._repository.transaction():
            if self._repository.get(draft_id) is not None:
                raise DraftError(
                    ErrorType.DUPLICATE_ORDER, "此草稿已提交过，不可重发。"
                )
            approval = self._gateway.require_current_approval(
                draft_id, as_of=now, in_transaction=True
            )
            draft = self._gateway.get_draft(draft_id)
            if draft is None or draft.broker is not Broker.SCHWAB:
                raise DraftError(
                    ErrorType.RISK_RULE_BLOCKED, "只支持 Schwab 模拟提交。"
                )
            attempt = self._repository.reserve(draft, approval, now)
        # 先持久化 SUBMITTING。进程中断后只能对账，不能重新进入提交路径。
        try:
            reply = self._adapter.submit(attempt.request)
        except Exception:
            return self._apply(attempt, None, now, reason="提交结果未确认")
        try:
            return self._apply(attempt, reply, now, reason="提交没有可核验回执")
        except (DraftError, ValidationError):
            return self._apply(
                attempt,
                None,
                now,
                reason="提交回执不符合核验规则",
                unverified_reply=reply,
            )

    def reconcile_order(
        self, draft_id: str, *, as_of: datetime | None = None
    ) -> SubmissionAttempt:
        now = _instant(as_of)
        with self._repository.transaction():
            attempt = self._repository.get(draft_id)
            if attempt is None:
                raise DraftError(ErrorType.DATA_MISSING, "没有可对账的提交尝试。")
            if now < attempt.updated_at:
                raise DraftError(
                    ErrorType.VALIDATION_ERROR, "对账时刻早于最新提交证据。"
                )
            if attempt.status is Status.SUBMITTING:
                if now - attempt.started_at < _RECOVERY_AGE:
                    raise DraftError(
                        ErrorType.RISK_RULE_BLOCKED,
                        "提交仍可能在处理中，暂不启动中断恢复。",
                    )
                attempt = self._repository.advance(
                    attempt,
                    Status.UNKNOWN,
                    now,
                    response={"simulation": "恢复中断的提交尝试"},
                )
            if attempt.status not in _CAN_RECONCILE:
                raise DraftError(
                    ErrorType.RISK_RULE_BLOCKED, "此提交状态不允许继续对账。"
                )
        # 即使关闭新提交，也必须能继续查证已有尝试。
        try:
            reply = self._adapter.lookup(attempt.request)
        except Exception:
            return self._apply(attempt, None, now, reason="对账读取未成功")
        try:
            return self._apply(attempt, reply, now, reason="未找到可确认结果的模拟证据")
        except (DraftError, ValidationError):
            self._apply(
                attempt,
                None,
                now,
                reason="对账回执不符合核验规则",
                unverified_reply=reply,
            )
            raise

    def _apply(
        self,
        attempt: SubmissionAttempt,
        reply: SimulatedReply | None,
        now: datetime,
        *,
        reason: str,
        unverified_reply: SimulatedReply | None = None,
    ) -> SubmissionAttempt:
        with self._repository.transaction():
            if self._repository.get(attempt.request.draft_id) != attempt:
                raise DraftError(
                    ErrorType.RISK_RULE_BLOCKED, "提交尝试已变更，请重新对账。"
                )
            if reply is None:
                status = (
                    Status.UNKNOWN
                    if attempt.status is Status.SUBMITTING
                    else attempt.status
                )
                response = {"simulation": reason}
                if unverified_reply is not None:
                    response["unverified_reply"] = unverified_reply.model_dump(
                        mode="json"
                    )
                return self._repository.advance(attempt, status, now, response=response)
            reply = SimulatedReply.model_validate(reply.model_dump())
            if reply.status is Status.FAILED and attempt.broker_order_id is not None:
                raise DraftError(
                    ErrorType.RISK_RULE_BLOCKED, "已接单的证据不能被改为未接单。"
                )
            if (
                attempt.status is Status.SUBMITTING
                and reply.status in _ACCEPTED_OUTCOMES
            ):
                attempt = self._repository.advance(
                    attempt,
                    Status.SUBMITTED,
                    now,
                    broker_order_id=reply.broker_order_id,
                )
            if reply.broker_order_id is not None and attempt.broker_order_id not in (
                None,
                reply.broker_order_id,
            ):
                raise DraftError(
                    ErrorType.VALIDATION_ERROR, "对账响应的券商订单 ID 与原证据不一致。"
                )
            for fill in reply.fills:
                self._repository.record_fill(attempt, fill, reply.broker_order_id, now)
            self._check_fill_status(attempt, reply.status)
            return self._repository.advance(
                attempt,
                reply.status,
                now,
                broker_order_id=reply.broker_order_id,
                response={
                    **reply.response,
                    "_simulation_evidence": reply.model_dump(
                        mode="json", exclude={"response"}
                    ),
                },
            )

    def _check_fill_status(self, attempt: SubmissionAttempt, status: Status) -> None:
        filled = self._db.execute(
            "SELECT coalesce(sum(quantity), 0) FROM broker_transaction "
            "WHERE draft_id = ? AND starts_with(transaction_id, 'SIM-FILL-')",
            [attempt.request.draft_id],
        ).fetchone()[0]
        ordered = attempt.request.order.quantity
        if (
            filled > ordered
            or (status is Status.FILLED and filled != ordered)
            or (status is Status.PARTIALLY_FILLED and not 0 < filled < ordered)
            or (
                status in (Status.SUBMITTED, Status.FAILED, Status.REJECTED)
                and filled != 0
            )
            or (status is Status.CANCELED and filled == ordered)
        ):
            raise DraftError(
                ErrorType.VALIDATION_ERROR, "模拟成交汇总与订单数量或返回状态不一致。"
            )


def _instant(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.utcoffset() is None:
        raise DraftError(ErrorType.VALIDATION_ERROR, "提交与对账时刻必须包含时区。")
    return value.astimezone(UTC)
