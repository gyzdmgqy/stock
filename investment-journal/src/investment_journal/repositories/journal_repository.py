import json
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import TypeVar

from duckdb import DuckDBPyConnection
from pydantic import BaseModel

from shared.db import get_journal_entry, get_trade_plan, insert_journal_entry
from shared.models import BrokerTransaction, JournalEntry, OrderDraft, TradePlan

from ..models import PerformanceReview, TradeOutcome

HORIZONS = (5, 20, 60)
Model = TypeVar("Model", bound=BaseModel)


def journal_key(kind: str, source_id: str) -> str:
    return f"JRN-{kind}-{source_id}"


def outcome_key(kind: str, source_id: str) -> str:
    return f"OUT-{kind}-{source_id}"


def _parameter(value):
    return value.value if isinstance(value, StrEnum) else value


class JournalRepository:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self.db = db

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.begin()
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _get(
        self,
        model: type[Model],
        table: str,
        key: str,
        value: str,
        *,
        json_fields: tuple[str, ...] = (),
    ) -> Model | None:
        columns = tuple(model.model_fields)
        row = self.db.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {key} = ?", [value]
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(columns, row, strict=True))
        for field in json_fields:
            if data[field] is not None:
                data[field] = json.loads(data[field])
        return model.model_validate(data)

    def require_plan(self, plan_id: str) -> TradePlan:
        plan = get_trade_plan(self.db, plan_id)
        if plan is None:
            raise ValueError(f"找不到交易计划 {plan_id}")
        return plan

    def require_draft(self, draft_id: str) -> OrderDraft:
        result = self._get(
            OrderDraft,
            "order_draft",
            "draft_id",
            draft_id,
            json_fields=("raw_payload",),
        )
        if result is None:
            raise ValueError(f"找不到订单草稿 {draft_id}")
        return result

    def require_transaction(self, transaction_id: str) -> BrokerTransaction:
        result = self._get(
            BrokerTransaction, "broker_transaction", "transaction_id", transaction_id
        )
        if result is None:
            raise ValueError(f"找不到券商记录 {transaction_id}")
        return result

    def record_entry(
        self,
        entry: JournalEntry,
        *,
        outcome_id: str | None = None,
        enrich_links: bool = False,
    ) -> JournalEntry:
        existing = get_journal_entry(self.db, entry.journal_id)
        if existing is None:
            if outcome_id and (outcome := self.get_outcome(outcome_id)) is not None:
                for horizon in HORIZONS:
                    setattr(
                        entry,
                        f"outcome_{horizon}d",
                        getattr(outcome, f"outcome_return_{horizon}d"),
                    )
            insert_journal_entry(self.db, entry)
        else:
            if entry.journal_id.startswith("JRN-APPROVAL-") and (
                existing.system_note != entry.system_note
                or existing.journal_date != entry.journal_date
            ):
                raise ValueError("同一审批 ID 的决策或日期发生冲突")
            for field in ("entry_type", "account_id", "symbol", "transaction_id"):
                if getattr(existing, field) != getattr(entry, field):
                    raise ValueError("日志事件 ID 对应的来源不一致")
            for field in ("plan_id", "draft_id"):
                if getattr(existing, field) not in (None, getattr(entry, field)):
                    raise ValueError("日志事件的计划或草稿关联冲突")
            if enrich_links and (existing.plan_id, existing.draft_id) != (
                entry.plan_id,
                entry.draft_id,
            ):
                self.db.execute(
                    """
                    UPDATE journal_entry SET plan_id = ?, draft_id = ?, action = ?,
                        strategy_type = ?, confidence = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE journal_id = ?
                    """,
                    [
                        entry.plan_id,
                        entry.draft_id,
                        _parameter(entry.action),
                        _parameter(entry.strategy_type),
                        entry.confidence,
                        entry.journal_id,
                    ],
                )
        return get_journal_entry(self.db, entry.journal_id)

    def link_transaction(
        self, transaction_id: str, plan_id: str | None, draft_id: str | None
    ) -> None:
        self.db.execute(
            "UPDATE broker_transaction SET plan_id = ?, draft_id = ? WHERE transaction_id = ?",
            [plan_id, draft_id, transaction_id],
        )
        self.db.execute(
            "UPDATE trade_outcome SET plan_id = ?, draft_id = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE transaction_id = ?",
            [plan_id, draft_id, transaction_id],
        )

    def get_outcome(self, outcome_id: str) -> TradeOutcome | None:
        return self._get(TradeOutcome, "trade_outcome", "outcome_id", outcome_id)

    def save_outcome(
        self, outcome: TradeOutcome, journal_id: str, *, invalidated: set[int]
    ) -> None:
        fields = outcome.model_dump(exclude={"created_at", "updated_at"})
        update_columns = ("plan_id", "draft_id")
        horizon_columns = tuple(
            key for key in fields if key.endswith(("5d", "20d", "60d"))
        )
        updates = [
            *(f"{key} = excluded.{key}" for key in update_columns),
            *(
                (
                    f"{key} = excluded.{key}"
                    if any(key.endswith(f"_{horizon}d") for horizon in invalidated)
                    else f"{key} = coalesce(excluded.{key}, trade_outcome.{key})"
                )
                for key in horizon_columns
            ),
            "updated_at = now()",
        ]
        self._upsert("trade_outcome", "outcome_id", fields, updates)
        persisted = self.get_outcome(outcome.outcome_id)
        self.db.execute(
            """
            UPDATE journal_entry SET outcome_5d = ?, outcome_20d = ?, outcome_60d = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE journal_id = ?
                AND (outcome_5d IS DISTINCT FROM ? OR outcome_20d IS DISTINCT FROM ?
                     OR outcome_60d IS DISTINCT FROM ?)
            """,
            [
                persisted.outcome_return_5d,
                persisted.outcome_return_20d,
                persisted.outcome_return_60d,
                journal_id,
                persisted.outcome_return_5d,
                persisted.outcome_return_20d,
                persisted.outcome_return_60d,
            ],
        )

    def save_review(self, review: PerformanceReview) -> PerformanceReview:
        fields = review.model_dump(exclude={"created_at"})
        updates = [
            f"{key} = excluded.{key}"
            for key in (
                "plan_count",
                "trade_count",
                "approved_count",
                "rejected_count",
                "summary",
            )
        ]
        self._upsert("performance_review", "review_id", fields, updates)
        return self._get(
            PerformanceReview, "performance_review", "review_id", review.review_id
        )

    def _upsert(self, table: str, key: str, fields: dict, updates: list[str]) -> None:
        self.db.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) "
            f"VALUES ({', '.join('?' for _ in fields)}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {', '.join(updates)}",
            [_parameter(value) for value in fields.values()],
        )
