from collections.abc import Sequence
from datetime import date
from math import isfinite

from duckdb import DuckDBPyConnection

from shared.enums import TransactionType

from ..models import TradeOutcome
from ..repositories.journal_repository import (
    HORIZONS,
    JournalRepository,
    journal_key,
    outcome_key,
)
from .journal_service import APP_TIMEZONE


def _excursions(reference: float, closes: list[float]) -> tuple[float, float]:
    peak = trough = reference
    drawdown = runup = 0.0
    for price in closes:
        peak, trough = max(peak, price), min(trough, price)
        drawdown = min(drawdown, price / peak - 1)
        runup = max(runup, price / trough - 1)
    return drawdown, runup


class OutcomeService:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._repository = JournalRepository(db)

    def evaluate_plan(
        self, plan_id: str, *, as_of: date, trading_sessions: Sequence[date]
    ) -> TradeOutcome | None:
        with self._repository.transaction():
            plan = self._repository.require_plan(plan_id)
            return self._evaluate(
                kind="PLAN",
                source_id=plan.plan_id,
                symbol=plan.symbol,
                account_id=plan.account_id,
                plan_id=plan.plan_id,
                draft_id=None,
                transaction_id=None,
                reference_date=plan.plan_date,
                fill_price=None,
                direction=1,
                as_of=as_of,
                trading_sessions=trading_sessions,
            )

    def evaluate_transaction(
        self, transaction_id: str, *, as_of: date, trading_sessions: Sequence[date]
    ) -> TradeOutcome | None:
        with self._repository.transaction():
            tx = self._repository.require_transaction(transaction_id)
            day = tx.trade_date
            if day is None and tx.transaction_time is not None:
                day = tx.transaction_time.astimezone(APP_TIMEZONE).date()
            if (
                tx.transaction_type not in (TransactionType.BUY, TransactionType.SELL)
                or not tx.symbol
                or tx.price is None
                or day is None
            ):
                return None
            return self._evaluate(
                kind="TRANSACTION",
                source_id=tx.transaction_id,
                symbol=tx.symbol,
                account_id=tx.account_id,
                plan_id=tx.plan_id,
                draft_id=tx.draft_id,
                transaction_id=tx.transaction_id,
                reference_date=day,
                fill_price=float(tx.price),
                direction=1 if tx.transaction_type is TransactionType.BUY else -1,
                as_of=as_of,
                trading_sessions=trading_sessions,
            )

    def _evaluate(
        self,
        *,
        kind: str,
        source_id: str,
        symbol: str,
        account_id: str,
        plan_id: str | None,
        draft_id: str | None,
        transaction_id: str | None,
        reference_date: date,
        fill_price: float | None,
        direction: int,
        as_of: date,
        trading_sessions: Sequence[date],
    ) -> TradeOutcome | None:
        sessions = tuple(trading_sessions)
        if tuple(sorted(set(sessions))) != sessions:
            raise ValueError("交易日历必须升序排列且无重复日期")
        if reference_date > as_of or reference_date not in sessions:
            return None
        start = sessions.index(reference_date)
        future = [
            day
            for day in sessions[start + 1 : start + max(HORIZONS) + 1]
            if day <= as_of
        ]
        cutoff = future[-1] if future else reference_date

        db = self._repository.db
        prices = {
            day: close
            for day, close in db.execute(
                """
                SELECT trade_date, close FROM daily_price
                WHERE symbol = ? AND trade_date BETWEEN ? AND ?
                """,
                [symbol, reference_date, cutoff],
            ).fetchall()
            if close is not None and isfinite(close) and close > 0
        }
        (split_date,) = db.execute(
            """
            SELECT min(event_date) FROM corporate_event WHERE symbol = ? AND event_type = 'SPLIT'
                AND event_date > ? AND event_date <= ?
            """,
            [symbol, reference_date, cutoff],
        ).fetchone()

        key = outcome_key(kind, source_id)
        existing = self._repository.get_outcome(key)
        if existing is not None and existing.reference_date != reference_date:
            raise ValueError("回看起算日期与已记录的口径不同")
        # 已记录的参考价固定下来，逐步回补窗口时使用同一基准。
        reference = (
            existing.reference_price
            if existing
            else (fill_price or prices.get(reference_date))
        )
        if reference is None:
            return None

        metrics = {}
        invalidated = set()
        for horizon in HORIZONS:
            days = future[:horizon]
            if len(days) < horizon:
                continue
            if split_date is not None and split_date <= days[-1]:
                invalidated.add(horizon)
                continue
            if days[-1] not in prices:
                continue
            close = prices[days[-1]]
            metrics.update(
                {
                    f"outcome_date_{horizon}d": days[-1],
                    f"outcome_price_{horizon}d": close,
                    f"outcome_return_{horizon}d": direction
                    * (close - reference)
                    / reference,
                }
            )
            if all(day in prices for day in days):
                drawdown, runup = _excursions(reference, [prices[day] for day in days])
                metrics[f"max_drawdown_{horizon}d"] = drawdown
                metrics[f"max_runup_{horizon}d"] = runup
        result = TradeOutcome(
            outcome_id=key,
            plan_id=plan_id,
            draft_id=draft_id,
            transaction_id=transaction_id,
            symbol=symbol,
            account_id=account_id,
            reference_date=reference_date,
            reference_price=reference,
            **metrics,
        )
        self._repository.save_outcome(
            result, journal_key(kind, source_id), invalidated=invalidated
        )
        return result
