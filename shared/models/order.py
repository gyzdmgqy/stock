from typing import Self

from pydantic import ConfigDict, JsonValue, model_validator

from shared.enums import ApprovalDecision as ApprovalDecisionType
from shared.enums import (
    Broker,
    OrderDraftStatus,
    OrderInstruction,
    OrderType,
    Session,
    TimeInForce,
)

from ._types import NonBlank, PositiveShares, Price, SharedModel, UtcDatetime

_PRICE_FIELDS = ("limit_price", "stop_price", "stop_limit_price")
_REQUIRED_ORDER_PRICES = {
    OrderType.MARKET: set(),
    OrderType.LIMIT: {"limit_price"},
    OrderType.STOP: {"stop_price"},
    OrderType.STOP_LIMIT: {"stop_price", "stop_limit_price"},
}
_APPROVAL_PROJECTIONS = {
    "approved_quantity": "quantity",
    "approved_limit_price": "limit_price",
    "approved_stop_price": "stop_price",
    "approved_stop_limit_price": "stop_limit_price",
}


class OrderSnapshot(SharedModel):
    model_config = ConfigDict(frozen=True)

    broker: Broker
    account_id: NonBlank
    symbol: NonBlank
    instruction: OrderInstruction
    order_type: OrderType
    quantity: PositiveShares
    limit_price: Price | None = None
    stop_price: Price | None = None
    stop_limit_price: Price | None = None
    time_in_force: TimeInForce
    session: Session

    @model_validator(mode="after")
    def validate_order_prices(self) -> Self:
        present = {field for field in _PRICE_FIELDS if getattr(self, field) is not None}
        required = _REQUIRED_ORDER_PRICES[self.order_type]
        if present != required:
            fields = ", ".join(sorted(required)) or "无"
            raise ValueError(f"{self.order_type} 需要的价格字段为 {fields}")
        return self


class ApprovalDecision(SharedModel):
    model_config = ConfigDict(frozen=True)

    approval_id: NonBlank
    draft_id: NonBlank
    plan_id: NonBlank
    decision: ApprovalDecisionType
    decision_note: str | None = None
    approved_quantity: PositiveShares | None = None
    approved_limit_price: Price | None = None
    approved_stop_price: Price | None = None
    approved_stop_limit_price: Price | None = None
    approved_payload: OrderSnapshot | None = None
    decided_at: UtcDatetime

    @model_validator(mode="after")
    def validate_approved_payload(self) -> Self:
        if self.decision is not ApprovalDecisionType.APPROVED:
            if self.approved_payload is not None or any(
                getattr(self, field) is not None for field in _APPROVAL_PROJECTIONS
            ):
                raise ValueError("仅批准决策可包含已批准的订单参数")
            return self

        if self.approved_payload is None:
            raise ValueError("批准决策必须包含完整的订单快照")

        for field, snapshot_field in _APPROVAL_PROJECTIONS.items():
            value = getattr(self.approved_payload, snapshot_field)
            if field in self.model_fields_set and getattr(self, field) != value:
                raise ValueError(f"{field} 与审批快照不一致")
            object.__setattr__(self, field, value)
        return self

    def _require_decision(
        self, draft: "OrderDraft", expected: ApprovalDecisionType
    ) -> None:
        if self.decision is not expected:
            raise ValueError(f"此迁移需要 {expected} 决策")
        if (self.draft_id, self.plan_id) != (draft.draft_id, draft.plan_id):
            raise ValueError("审批决策必须属于当前草稿和交易计划")
        if (
            expected is ApprovalDecisionType.APPROVED
            and self.approved_payload != draft.order_snapshot()
        ):
            raise ValueError("审批快照与当前草稿的订单参数不一致")


class OrderDraft(OrderSnapshot):
    draft_id: NonBlank
    plan_id: NonBlank
    time_in_force: TimeInForce = TimeInForce.DAY
    session: Session = Session.NORMAL
    replaces_draft_id: NonBlank | None = None
    status: OrderDraftStatus = OrderDraftStatus.PENDING_REVIEW
    broker_order_id: NonBlank | None = None
    raw_payload: dict[str, JsonValue] | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def validate_replacement_link(self) -> Self:
        if self.replaces_draft_id == self.draft_id:
            raise ValueError("草稿不能替换自身")
        return self

    def order_snapshot(self) -> OrderSnapshot:
        return OrderSnapshot.model_validate(
            self.model_dump(include=set(OrderSnapshot.model_fields))
        )

    def transition_to(
        self,
        target: OrderDraftStatus | str,
        *,
        approval: ApprovalDecision | None = None,
    ) -> Self:
        status = OrderDraftStatus(target)
        self._require_transition(status)
        if status is OrderDraftStatus.MODIFIED:
            raise ValueError("修改必须通过 replace_with 同时生成待审草稿")
        decision = self._required_review(status)
        if decision is not None:
            if approval is None:
                raise ValueError(f"此迁移需要 {decision} 决策")
            approval._require_decision(self, decision)
        return type(self).model_validate({**self.model_dump(), "status": status})

    def replace_with(
        self, replacement: Self, approval: ApprovalDecision
    ) -> tuple[Self, Self]:
        self._require_transition(OrderDraftStatus.MODIFIED)
        approval._require_decision(self, ApprovalDecisionType.MODIFIED)
        if replacement.draft_id == self.draft_id or replacement.plan_id != self.plan_id:
            raise ValueError("替换草稿必须使用新 ID 并关联同一交易计划")
        if (
            replacement.status is not OrderDraftStatus.PENDING_REVIEW
            or replacement.broker_order_id is not None
        ):
            raise ValueError("替换草稿必须尚未审批或提交")
        if replacement.replaces_draft_id not in (None, self.draft_id):
            raise ValueError("替换草稿已关联其他草稿")

        retired = type(self).model_validate(
            {**self.model_dump(), "status": OrderDraftStatus.MODIFIED}
        )
        new = type(self).model_validate(
            {
                **replacement.model_dump(),
                "replaces_draft_id": self.draft_id,
                "raw_payload": None,
            }
        )
        return retired, new

    def _require_transition(self, status: OrderDraftStatus) -> None:
        if not self.status.allows(status):
            raise ValueError(f"订单草稿不能从 {self.status} 转为 {status}")

    def _required_review(self, status: OrderDraftStatus) -> ApprovalDecisionType | None:
        if status in (OrderDraftStatus.APPROVED, OrderDraftStatus.SUBMITTING):
            return ApprovalDecisionType.APPROVED
        if status is OrderDraftStatus.DEFERRED:
            return ApprovalDecisionType.DEFERRED
        if status is OrderDraftStatus.REJECTED and self.status in (
            OrderDraftStatus.PENDING_REVIEW,
            OrderDraftStatus.DEFERRED,
        ):
            return ApprovalDecisionType.REJECTED
        return None
