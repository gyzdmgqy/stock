from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.enums import OrderDraftStatus, TradePlanStatus
from shared.models import ApprovalDecision, OrderDraft, TradePlan


@pytest.fixture
def draft():
    return OrderDraft(
        draft_id="OD-1",
        plan_id="TP-1",
        broker="MANUAL",
        account_id="ACCT-1",
        symbol="VOO",
        instruction="BUY",
        order_type="LIMIT",
        quantity="1.25",
        limit_price="510.00",
    )


def review(draft, decision="APPROVED"):
    return ApprovalDecision(
        approval_id=f"APR-{draft.draft_id}-{decision}",
        draft_id=draft.draft_id,
        plan_id=draft.plan_id,
        decision=decision,
        decided_at="2026-06-05T21:00:00Z",
        approved_payload=draft.order_snapshot() if decision == "APPROVED" else None,
    )


@pytest.mark.parametrize(
    ("current", "allowed"),
    [
        ("DRAFT", {"REVIEWED", "EXPIRED"}),
        ("REVIEWED", {"APPROVED", "REJECTED", "EXPIRED"}),
        ("APPROVED", {"EXECUTED", "EXPIRED"}),
        ("REJECTED", set()),
        ("EXPIRED", set()),
        ("EXECUTED", set()),
    ],
)
def test_plan_lifecycle_matrix(current, allowed):
    assert {
        status.value
        for status in TradePlanStatus
        if TradePlanStatus(current).allows(status)
    } == allowed


@pytest.mark.parametrize(
    ("current", "allowed"),
    [
        ("PENDING_REVIEW", {"APPROVED", "REJECTED", "DEFERRED", "MODIFIED", "EXPIRED"}),
        ("DEFERRED", {"PENDING_REVIEW", "REJECTED", "MODIFIED", "EXPIRED"}),
        ("APPROVED", {"SUBMITTING", "MODIFIED", "EXPIRED"}),
        ("SUBMITTING", {"SUBMITTED", "REJECTED", "FAILED", "UNKNOWN"}),
        (
            "UNKNOWN",
            {
                "SUBMITTED",
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELED",
                "REJECTED",
                "FAILED",
            },
        ),
        (
            "SUBMITTED",
            {"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "UNKNOWN"},
        ),
        ("PARTIALLY_FILLED", {"PARTIALLY_FILLED", "FILLED", "CANCELED", "UNKNOWN"}),
        ("REJECTED", set()),
        ("MODIFIED", set()),
        ("EXPIRED", set()),
        ("FILLED", set()),
        ("CANCELED", set()),
        ("FAILED", set()),
    ],
)
def test_draft_lifecycle_matrix(current, allowed):
    assert {
        status.value
        for status in OrderDraftStatus
        if OrderDraftStatus(current).allows(status)
    } == allowed


def test_plan_cannot_skip_review():
    plan = TradePlan(
        plan_id="TP-1",
        symbol="VOO",
        plan_date="2026-06-05",
        account_id="ACCT-1",
        account_role="CORE_PASSIVE",
        action="WATCH",
    )
    with pytest.raises(ValueError):
        plan.transition_to("APPROVED")
    assert (
        plan.transition_to("REVIEWED").transition_to("APPROVED").status
        is TradePlanStatus.APPROVED
    )
    assert plan.status is TradePlanStatus.DRAFT


def test_submit_requires_matching_approval_and_unknown_requires_reconciliation(draft):
    approval = review(draft)
    with pytest.raises(ValueError):
        draft.transition_to("SUBMITTING", approval=approval)
    with pytest.raises(ValueError):
        draft.transition_to("APPROVED")

    approved = draft.transition_to("APPROVED", approval=approval)
    with pytest.raises(ValueError):
        approved.transition_to("SUBMITTING")
    submitted = approved.transition_to("SUBMITTING", approval=approval)
    unknown = submitted.transition_to("UNKNOWN")
    with pytest.raises(ValueError):
        unknown.transition_to("SUBMITTING", approval=approval)
    assert unknown.transition_to("FILLED").status is OrderDraftStatus.FILLED


def test_modification_retires_old_draft_and_requires_fresh_approval(draft):
    old_approval = review(draft)
    approved = draft.transition_to("APPROVED", approval=old_approval)
    replacement = OrderDraft.model_validate(
        {**draft.model_dump(), "draft_id": "OD-2", "limit_price": "509.50"}
    )

    with pytest.raises(ValueError):
        approved.transition_to("MODIFIED")
    with pytest.raises(ValueError):
        approved.replace_with(replacement, old_approval)
    with pytest.raises(ValueError):
        approved.replace_with(draft, review(draft, "MODIFIED"))
    retired, new = approved.replace_with(replacement, review(draft, "MODIFIED"))
    assert retired.status is OrderDraftStatus.MODIFIED
    assert new.status is OrderDraftStatus.PENDING_REVIEW
    assert new.replaces_draft_id == draft.draft_id
    assert new.limit_price == Decimal("509.50")
    with pytest.raises(ValueError):
        new.transition_to("APPROVED", approval=old_approval)
    with pytest.raises(ValueError):
        retired.transition_to("SUBMITTING", approval=old_approval)
    assert (
        new.transition_to("APPROVED", approval=review(new)).status
        is OrderDraftStatus.APPROVED
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "ACCT-2"),
        ("symbol", "QQQ"),
        ("instruction", "SELL"),
        ("order_type", "MARKET"),
        ("quantity", "2"),
        ("limit_price", "511.00"),
        ("session", "EXTENDED"),
        ("time_in_force", "GTC"),
        ("broker", "SCHWAB"),
    ],
)
def test_approval_binds_all_order_fields(draft, field, value):
    approved = draft.transition_to("APPROVED", approval=review(draft))
    changes = {field: value}
    if field == "order_type":
        changes["limit_price"] = None
    changed = OrderDraft.model_validate({**approved.model_dump(), **changes})
    with pytest.raises(ValueError):
        changed.transition_to("SUBMITTING", approval=review(draft))


def test_approval_snapshot_and_projections_are_immutable(draft):
    approval = review(draft)
    assert approval.approved_quantity == draft.quantity
    assert approval.approved_limit_price == draft.limit_price
    with pytest.raises(ValidationError):
        approval.approved_payload.quantity = Decimal("100")
    with pytest.raises(ValidationError):
        draft.quantity = Decimal("100")
    with pytest.raises(ValidationError):
        ApprovalDecision.model_validate(
            {**approval.model_dump(), "approved_quantity": "100"}
        )


@pytest.mark.parametrize("missing", ["time_in_force", "session"])
def test_approval_cannot_fill_in_unreviewed_execution_terms(draft, missing):
    record = review(draft).model_dump()
    del record["approved_payload"][missing]
    with pytest.raises(ValidationError):
        ApprovalDecision.model_validate(record)


def test_human_rejection_and_deferral_require_matching_decision(draft):
    with pytest.raises(ValueError):
        draft.transition_to("DEFERRED", approval=review(draft, "REJECTED"))
    deferred = draft.transition_to("DEFERRED", approval=review(draft, "DEFERRED"))
    assert (
        deferred.transition_to("PENDING_REVIEW").status
        is OrderDraftStatus.PENDING_REVIEW
    )
    with pytest.raises(ValueError):
        deferred.transition_to("REJECTED")
    assert (
        deferred.transition_to("REJECTED", approval=review(draft, "REJECTED")).status
        is OrderDraftStatus.REJECTED
    )
