from datetime import date, timedelta

import pandas as pd
import pytest

from investment_journal.services.journal_service import JournalService
from investment_journal.services.outcome_service import OutcomeService
from investment_journal.services.performance_review_service import (
    PerformanceReviewService,
)
from shared.db import (
    connect_database,
    get_journal_entry,
    initialize_database,
    insert_trade_plan,
)
from shared.enums import JournalEntryType
from shared.models import (
    ApprovalDecision,
    BrokerTransaction,
    DailyCioBrief,
    DailySignal,
    OrderDraft,
    TradePlan,
)

REFERENCE = date(2026, 6, 5)
SESSIONS = tuple(pd.bdate_range(start=REFERENCE, periods=61).date)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "journal.duckdb"
    initialize_database(path)
    with connect_database(path) as connection:
        yield connection


@pytest.fixture
def plan(db):
    plan = TradePlan(
        plan_id="TP-1",
        symbol="VRTX",
        plan_date=REFERENCE,
        account_id="SCHWAB_ROTH",
        account_role="ACTIVE_TRADING",
        action="RE_ENTRY",
        strategy_type="FALSE_BREAKDOWN_REENTRY",
        status="REJECTED",
        thesis="回测计划",
        reason="理由",
        confidence=85,
        entry_order={"type": "LIMIT", "price": 88},
        invalid_condition=["break_support"],
    )
    insert_trade_plan(db, plan)
    return plan


@pytest.fixture
def draft(db, plan):
    model = OrderDraft(
        draft_id="OD-1",
        plan_id=plan.plan_id,
        broker="SCHWAB",
        account_id=plan.account_id,
        symbol=plan.symbol,
        instruction="BUY",
        order_type="LIMIT",
        limit_price=88,
        quantity=2,
        created_at="2026-06-05T20:00:00Z",
    )
    db.execute(
        """
        INSERT INTO order_draft (
            draft_id, plan_id, broker, account_id, symbol, instruction,
            order_type, limit_price, quantity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            model.draft_id,
            model.plan_id,
            model.broker.value,
            model.account_id,
            model.symbol,
            model.instruction.value,
            model.order_type.value,
            model.limit_price,
            model.quantity,
            model.created_at,
        ],
    )
    return model


def store_transaction(
    db, *, draft_id=None, transaction_type="BUY", transaction_id="TX-1"
):
    tx = BrokerTransaction(
        transaction_id=transaction_id,
        broker="SCHWAB",
        account_id="SCHWAB_ROTH",
        symbol="VRTX",
        transaction_type=transaction_type,
        quantity=2,
        price=80,
        fee=14,
        trade_date=REFERENCE,
        source="CSV",
        deduplication_key=transaction_id,
        draft_id=draft_id,
    )
    db.execute(
        """
        INSERT INTO broker_transaction (
            transaction_id, broker, account_id, symbol, transaction_type, quantity,
            price, fee, trade_date, source, deduplication_key, draft_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            tx.transaction_id,
            tx.broker.value,
            tx.account_id,
            tx.symbol,
            tx.transaction_type.value,
            tx.quantity,
            tx.price,
            tx.fee,
            tx.trade_date,
            tx.source.value,
            tx.deduplication_key,
            draft_id,
        ],
    )
    return tx


def store_prices(db, *, skip=()):
    db.executemany(
        "INSERT INTO daily_price (symbol, trade_date, close, adjusted_close) VALUES ('VRTX', ?, ?, ?)",
        [(day, 100 + i, 50 + i) for i, day in enumerate(SESSIONS) if i not in skip],
    )


def test_record_plan_is_idempotent_and_keeps_notes(db, plan):
    service = JournalService(db)
    first = service.record_plan(plan)
    assert first.entry_type is JournalEntryType.TRADE_PLAN_REVIEW
    assert first.plan_id == plan.plan_id
    assert first.strategy_type == plan.strategy_type
    assert first.thesis == plan.thesis
    db.execute(
        "UPDATE journal_entry SET user_note = '保留备注' WHERE journal_id = ?",
        [first.journal_id],
    )
    assert service.record_plan(plan).user_note == "保留备注"
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (1,)


def test_draft_and_rejection_are_distinct_events(db, draft):
    service = JournalService(db)
    first = service.record_draft(draft)
    decision = ApprovalDecision(
        approval_id="APR-1",
        draft_id=draft.draft_id,
        plan_id=draft.plan_id,
        decision="REJECTED",
        decision_note="价格未确认",
        decided_at="2026-06-06T01:00:00Z",
    )
    second = service.record_approval(decision)
    assert second.entry_type is JournalEntryType.ORDER_REVIEW
    assert second.journal_date == REFERENCE
    assert second.decision_reason == "价格未确认"
    assert second.draft_id == draft.draft_id
    assert second.journal_id != first.journal_id
    assert service.record_approval(decision) == second
    with pytest.raises(ValueError, match="审批"):
        service.record_approval(
            ApprovalDecision.model_validate(
                {**decision.model_dump(), "decision": "DEFERRED"}
            )
        )


def test_approved_snapshot_must_match_order(db, draft):
    decision = ApprovalDecision(
        approval_id="APR-1",
        draft_id=draft.draft_id,
        plan_id=draft.plan_id,
        decision="APPROVED",
        decided_at="2026-06-05T21:00:00Z",
        approved_payload={**draft.order_snapshot().model_dump(), "quantity": 3},
    )
    with pytest.raises(ValueError, match="快照"):
        JournalService(db).record_approval(decision)
    entry = JournalService(db).record_approval(
        ApprovalDecision(
            approval_id="APR-2",
            draft_id=draft.draft_id,
            plan_id=draft.plan_id,
            decision="APPROVED",
            decided_at=decision.decided_at,
            approved_payload=draft.order_snapshot(),
        )
    )
    assert entry.system_note == "审批结果 APPROVED"


def test_signal_and_brief_can_be_recorded(db):
    service = JournalService(db)
    signal = DailySignal(
        signal_id="SIG-1", symbol="VRTX", trade_date=REFERENCE, reason="形态观察"
    )
    brief = DailyCioBrief(
        brief_id="BRIEF-1",
        brief_date=REFERENCE,
        final_recommendation="观察",
        market_summary={"market_regime": "RANGE", "confidence": 75},
    )
    assert service.record_signal(signal).entry_type is JournalEntryType.SIGNAL_REVIEW
    entry = service.record_brief(brief)
    assert entry.entry_type is JournalEntryType.DAILY
    assert entry.confidence == 75
    assert service.record_brief(brief) == entry


def test_transaction_links_to_plan_via_draft_and_already_linked_records_are_preserved(
    db, draft
):
    tx = store_transaction(db, draft_id=draft.draft_id)
    service = JournalService(db)
    entry = service.record_transaction(tx)
    assert entry.entry_type is JournalEntryType.TRADE_EXECUTION
    assert entry.plan_id == draft.plan_id
    assert entry.draft_id == draft.draft_id
    assert entry.transaction_id == tx.transaction_id
    assert db.execute(
        "SELECT plan_id, draft_id FROM broker_transaction WHERE transaction_id = ?",
        [tx.transaction_id],
    ).fetchone() == (draft.plan_id, draft.draft_id)
    assert service.record_transaction(tx) == entry


def test_linking_an_existing_fill_keeps_notes_and_blocks_cross_account_plan(db, plan):
    tx = store_transaction(db)
    service = JournalService(db)
    first = service.record_transaction(tx)
    db.execute(
        "UPDATE journal_entry SET user_note = '保留备注' WHERE journal_id = ?",
        [first.journal_id],
    )
    other = TradePlan.model_validate(
        {
            **plan.model_dump(),
            "plan_id": "TP-OTHER",
            "account_id": "VANGUARD_ROTH",
            "account_role": "CORE_PASSIVE",
        }
    )
    insert_trade_plan(db, other)
    with pytest.raises(ValueError, match="账户"):
        service.record_transaction(tx, plan_id=other.plan_id)
    assert get_journal_entry(db, first.journal_id).plan_id is None

    linked = service.record_transaction(tx, plan_id=plan.plan_id)
    assert linked.plan_id == plan.plan_id
    assert linked.user_note == "保留备注"
    assert linked.journal_id == first.journal_id


def test_rejected_plan_uses_plan_day_close_and_all_three_trading_day_windows(db, plan):
    store_prices(db)
    entry = JournalService(db).record_plan(plan)
    result = OutcomeService(db).evaluate_plan(
        plan.plan_id, as_of=SESSIONS[60], trading_sessions=SESSIONS
    )
    assert result.reference_price == 100
    for horizon in (5, 20, 60):
        assert getattr(result, f"outcome_date_{horizon}d") == SESSIONS[horizon]
        assert getattr(result, f"outcome_return_{horizon}d") == pytest.approx(
            horizon / 100
        )
        assert getattr(result, f"max_drawdown_{horizon}d") == 0
        assert getattr(result, f"max_runup_{horizon}d") == pytest.approx(horizon / 100)
    assert get_journal_entry(db, entry.journal_id).outcome_60d == pytest.approx(0.6)
    assert db.execute("SELECT count(*) FROM trade_outcome").fetchone() == (1,)


def test_missing_trading_day_and_as_of_do_not_shift_or_erase_horizons(db, plan):
    store_prices(db, skip=(15, 20))
    service = OutcomeService(db)
    full = service.evaluate_plan(
        plan.plan_id, as_of=SESSIONS[-1], trading_sessions=SESSIONS
    )
    assert full.outcome_date_5d == SESSIONS[5]
    assert full.outcome_date_20d is None
    assert full.outcome_date_60d == SESSIONS[60]
    assert full.outcome_return_60d == pytest.approx(0.6)
    assert full.max_drawdown_60d is None
    assert full.max_runup_60d is None
    partial = service.evaluate_plan(
        plan.plan_id, as_of=SESSIONS[3], trading_sessions=SESSIONS
    )
    assert partial.outcome_date_5d is None
    assert db.execute("SELECT outcome_date_5d FROM trade_outcome").fetchone() == (
        SESSIONS[5],
    )


def test_split_record_invalidates_windows_crossing_it(db, plan):
    store_prices(db)
    entry = JournalService(db).record_plan(plan)
    service = OutcomeService(db)
    service.evaluate_plan(plan.plan_id, as_of=SESSIONS[-1], trading_sessions=SESSIONS)
    db.execute(
        "INSERT INTO corporate_event (event_id, symbol, event_date, event_type) "
        "VALUES ('SPLIT-1', 'VRTX', ?, 'SPLIT')",
        [SESSIONS[10]],
    )
    result = service.evaluate_plan(
        plan.plan_id, as_of=SESSIONS[-1], trading_sessions=SESSIONS
    )
    assert result.outcome_return_5d == pytest.approx(0.05)
    assert result.outcome_return_20d is None
    stored = get_journal_entry(db, entry.journal_id)
    assert stored.outcome_20d is None
    assert stored.outcome_60d is None


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_execution_uses_fill_price_and_keeps_outcome_separate_from_plan(
    db, plan, side, sign
):
    store_prices(db)
    tx = store_transaction(db, transaction_type=side)
    journal = JournalService(db).record_transaction(tx, plan_id=plan.plan_id)
    service = OutcomeService(db)
    plan_out = service.evaluate_plan(
        plan.plan_id, as_of=SESSIONS[5], trading_sessions=SESSIONS
    )
    result = service.evaluate_transaction(
        tx.transaction_id, as_of=SESSIONS[5], trading_sessions=SESSIONS
    )
    assert result.outcome_id != plan_out.outcome_id
    assert result.reference_price == 80
    assert result.outcome_return_5d == pytest.approx(sign * 25 / 80)
    assert get_journal_entry(db, journal.journal_id).outcome_5d == pytest.approx(
        sign * 25 / 80
    )
    assert db.execute("SELECT count(*) FROM trade_outcome").fetchone() == (2,)


def test_review_skeleton_persists_period_and_benchmark_placeholders(db, plan, draft):
    service = JournalService(db)
    service.record_approval(
        ApprovalDecision(
            approval_id="APR-1",
            draft_id=draft.draft_id,
            plan_id=plan.plan_id,
            decision="REJECTED",
            decided_at="2026-06-05T21:00:00Z",
        )
    )
    store_transaction(db)
    review_service = PerformanceReviewService(db)
    start = REFERENCE - timedelta(days=4)
    end = REFERENCE + timedelta(days=2)
    review = review_service.weekly_review(start, end, account_id="SCHWAB_ROTH")
    assert (
        review.plan_count,
        review.trade_count,
        review.approved_count,
        review.rejected_count,
    ) == (1, 1, 0, 1)
    assert all(ticker in review.summary for ticker in ("VOO", "QQQ", "SPY"))
    assert review.win_rate is None
    assert (
        review_service.weekly_review(start, end, account_id="SCHWAB_ROTH").review_id
        == review.review_id
    )
    monthly = review_service.monthly_review(date(2026, 6, 1), date(2026, 6, 30))
    assert monthly.review_type == "MONTHLY"
    assert db.execute("SELECT count(*) FROM performance_review").fetchone() == (2,)


def test_vanguard_progress_compares_observed_holdings(db):
    end = SESSIONS[5]
    db.executemany(
        """
        INSERT INTO portfolio_position_snapshot
        (snapshot_id, account_id, snapshot_date, symbol, quantity, market_value)
        VALUES (?, 'VANGUARD_ROTH', ?, ?, ?, ?)
        """,
        [
            ("P1", REFERENCE, "VRTX", 2, 200),
            ("P2", REFERENCE, "AAPL", 5, 500),
            ("P3", end, "AAPL", 3, 300),
            ("P4", end, "VOO", 2, 1000),
            ("P5", end, "QQQ", 1, 500),
        ],
    )
    result = PerformanceReviewService(db).vanguard_progress(
        "VANGUARD_ROTH", REFERENCE, end
    )
    assert (result.initial_stock_count, result.current_stock_count) == (2, 1)
    assert (result.initial_stock_value, result.current_stock_value) == (700, 300)
    assert result.voo_qqq_ratio == 2
