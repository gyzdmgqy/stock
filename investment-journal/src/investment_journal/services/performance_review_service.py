from datetime import date
from hashlib import sha256
from json import dumps

from duckdb import DuckDBPyConnection

from shared.enums import ApprovalDecision as ApprovalDecisionType
from shared.enums import ReviewType

from ..models import PerformanceReview
from ..reports.monthly_review import render_monthly_review
from ..reports.weekly_review import VanguardProgress, render_weekly_review
from ..repositories.journal_repository import JournalRepository
from .journal_service import approval_note


class PerformanceReviewService:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._repository = JournalRepository(db)

    def weekly_review(
        self, period_start: date, period_end: date, *, account_id: str | None = None
    ) -> PerformanceReview:
        return self._review(ReviewType.WEEKLY, period_start, period_end, account_id)

    def monthly_review(
        self, period_start: date, period_end: date, *, account_id: str | None = None
    ) -> PerformanceReview:
        return self._review(ReviewType.MONTHLY, period_start, period_end, account_id)

    def _review(
        self, kind: ReviewType, start: date, end: date, account_id: str | None
    ) -> PerformanceReview:
        if start > end:
            raise ValueError("复盘起始日期不能晚于结束日期")
        db = self._repository.db
        with self._repository.transaction():
            vanguard = (
                account_id is not None
                and self._account_broker(account_id) == "VANGUARD"
            )
            (plans,) = db.execute(
                "SELECT count(*) FROM trade_plan WHERE plan_date BETWEEN ? AND ? "
                "AND (? IS NULL OR account_id = ?)",
                [start, end, account_id, account_id],
            ).fetchone()
            (buys_sells,) = db.execute(
                """
                SELECT count(*) FROM broker_transaction
                WHERE transaction_type IN ('BUY', 'SELL')
                    AND coalesce(trade_date, CAST(transaction_time AT TIME ZONE 'America/Chicago' AS DATE))
                        BETWEEN ? AND ?
                    AND (? IS NULL OR account_id = ?)
                """,
                [start, end, account_id, account_id],
            ).fetchone()
            approved, rejected = db.execute(
                """
                SELECT count(*) FILTER (WHERE system_note = ?), count(*) FILTER (WHERE system_note = ?)
                FROM journal_entry WHERE entry_type = 'ORDER_REVIEW'
                    AND starts_with(journal_id, 'JRN-APPROVAL-')
                    AND journal_date BETWEEN ? AND ? AND (? IS NULL OR account_id = ?)
                """,
                [
                    approval_note(ApprovalDecisionType.APPROVED),
                    approval_note(ApprovalDecisionType.REJECTED),
                    start,
                    end,
                    account_id,
                    account_id,
                ],
            ).fetchone()
            account_key = sha256(dumps(account_id).encode("utf-8")).hexdigest()[:16]
            review = PerformanceReview(
                review_id=f"REV-{kind}-{start:%Y%m%d}-{end:%Y%m%d}-{account_key}",
                review_date=end,
                review_type=kind,
                account_id=account_id,
                period_start=start,
                period_end=end,
                plan_count=plans,
                trade_count=buys_sells,
                approved_count=approved,
                rejected_count=rejected,
            )
            progress = (
                self.vanguard_progress(account_id, start, end) if vanguard else None
            )
            render = (
                render_weekly_review
                if kind is ReviewType.WEEKLY
                else render_monthly_review
            )
            review.summary = render(review, progress)
            return self._repository.save_review(review)

    def _account_broker(self, account_id: str) -> str:
        row = self._repository.db.execute(
            "SELECT broker FROM portfolio_account WHERE account_id = ?", [account_id]
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到账户 {account_id}")
        return row[0]

    def vanguard_progress(
        self, account_id: str, start: date, end: date
    ) -> VanguardProgress:
        if start > end:
            raise ValueError("持仓比较起始日期不能晚于结束日期")
        if self._account_broker(account_id) != "VANGUARD":
            raise ValueError("迁移进度仅适用于 Vanguard 账户")
        initial, current = self._repository.db.execute(
            """
            SELECT min(snapshot_date), max(snapshot_date) FROM portfolio_position_snapshot
            WHERE account_id = ? AND snapshot_date BETWEEN ? AND ?
            """,
            [account_id, start, end],
        ).fetchone()
        if initial is None:
            return VanguardProgress()
        initial_count, initial_value, _, _ = self._holdings(account_id, initial)
        current_count, current_value, voo, qqq = self._holdings(account_id, current)
        return VanguardProgress(
            initial,
            current,
            initial_count,
            current_count,
            initial_value,
            current_value,
            voo,
            qqq,
        )

    def _holdings(self, account_id: str, day: date) -> tuple:
        return self._repository.db.execute(
            """
            WITH latest AS (
                SELECT p.symbol, s.asset_type, p.quantity, p.market_value
                FROM portfolio_position_snapshot p LEFT JOIN symbol s USING (symbol)
                WHERE p.account_id = ? AND p.snapshot_date = ?
                QUALIFY row_number() OVER (
                    PARTITION BY p.symbol ORDER BY p.observed_at DESC NULLS LAST,
                    p.created_at DESC NULLS LAST, p.snapshot_id DESC
                ) = 1
            )
            SELECT
                CASE WHEN count(*) FILTER (WHERE quantity IS NULL OR (quantity > 0 AND asset_type IS NULL)) > 0
                    THEN NULL ELSE count(*) FILTER (WHERE asset_type = 'STOCK' AND quantity > 0) END,
                CASE WHEN count(*) FILTER (WHERE quantity IS NULL OR (quantity > 0 AND (
                    asset_type IS NULL OR (asset_type = 'STOCK' AND market_value IS NULL)))) > 0
                    THEN NULL ELSE coalesce(sum(market_value) FILTER (
                        WHERE asset_type = 'STOCK' AND quantity > 0
                    ), 0) END,
                max(market_value) FILTER (WHERE symbol = 'VOO' AND quantity > 0),
                max(market_value) FILTER (WHERE symbol = 'QQQ' AND quantity > 0)
            FROM latest
            """,
            [account_id, day],
        ).fetchone()
