from duckdb import DuckDBPyConnection

from shared.enums import ErrorType, OrderDraftStatus
from shared.models import OrderDraft

from .order_draft_validator import DraftError

_ACTIVE = tuple(
    status.value
    for status in (
        OrderDraftStatus.PENDING_REVIEW,
        OrderDraftStatus.APPROVED,
        OrderDraftStatus.DEFERRED,
        OrderDraftStatus.SUBMITTING,
        OrderDraftStatus.SUBMITTED,
        OrderDraftStatus.PARTIALLY_FILLED,
        OrderDraftStatus.UNKNOWN,
    )
)


def require_no_duplicate(
    db: DuckDBPyConnection, draft: OrderDraft, *, replacing: str | None = None
) -> None:
    conflict = db.execute(
        """
        SELECT 1 FROM order_draft
        WHERE account_id = ? AND symbol = ? AND instruction = ?
        AND draft_id IS DISTINCT FROM ?
        AND (
            status IN (SELECT unnest(?))
            OR (? IS NULL AND plan_id = ? AND order_type = ?
                AND limit_price IS NOT DISTINCT FROM ?)
        )
        LIMIT 1
        """,
        [
            draft.account_id,
            draft.symbol,
            draft.instruction.value,
            replacing,
            list(_ACTIVE),
            replacing,
            draft.plan_id,
            draft.order_type.value,
            draft.limit_price,
        ],
    ).fetchone()
    if conflict:
        raise DraftError(
            ErrorType.DUPLICATE_ORDER,
            "同一计划存在重复草稿，或该账户标的同方向已有未解决订单。",
        )
