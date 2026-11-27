import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from broker_gateway.drafts import DraftError, OrderDraftService
from broker_gateway.submission import (
    SimulatedFill,
    SimulatedReply,
    SimulatedSchwabAdapter,
    SubmissionPolicy,
    SubmissionService,
)
from shared.db import connect_database, initialize_database
from shared.enums import ApprovalDecision as Decision
from shared.enums import ErrorType
from shared.enums import OrderDraftStatus as Status
from shared.models import IntradaySignal, OrderSnapshot
from trade_planner.planners.base import EntryPrices, PlanningRequest, PortfolioState
from trade_planner.services.trade_plan_service import TradePlanService

DAY = date(2026, 6, 8)
NOW = datetime(2026, 6, 8, 20, 15, tzinfo=UTC)
SESSIONS = (
    date(2026, 6, 5),
    DAY,
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
    date(2026, 6, 12),
    date(2026, 6, 15),
)
ENABLED = SubmissionPolicy.from_env(
    {"ORDER_SUBMISSION_ENABLED": "true"}, phase12_verified=True
)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "orders.simulation.duckdb"
    initialize_database(path)
    with connect_database(path) as db:
        yield db


def draft_for(db, *, buy=False):
    for day in SESSIONS[:2]:
        db.execute(
            "INSERT INTO daily_price (symbol, trade_date, close) VALUES ('VRTX', ?, 90)",
            [day],
        )
        db.execute(
            "INSERT INTO daily_indicator (symbol, trade_date, ma200) VALUES ('VRTX', ?, 100)",
            [day],
        )
    db.execute(
        "INSERT INTO daily_signal (signal_id, symbol, trade_date, confidence, market_regime, "
        "false_breakdown_score, volume_confirmation_score) VALUES ('signal', 'VRTX', ?, 85, 'RANGE', 90, 90)",
        [DAY],
    )
    request = PlanningRequest(
        account_id="SCHWAB_ROTH",
        signal_id="signal",
        as_of=NOW,
        trading_sessions=SESSIONS,
        exit_limit_price=90,
        reentry_candidate=buy,
        earnings_checked_through=SESSIONS[-1],
        entry_prices=(
            EntryPrices(limit_price=100, stop_price=95, target_price=115)
            if buy
            else None
        ),
        intraday_signal=(
            IntradaySignal(
                signal_id="h1",
                symbol="VRTX",
                trade_date=DAY,
                bar_start="2026-06-08T18:30:00Z",
                hourly_trend="HIGHER_LOW_CONFIRMED",
                vwap_status="ABOVE_VWAP",
            )
            if buy
            else None
        ),
        portfolio=PortfolioState(
            account_id="SCHWAB_ROTH",
            symbol="VRTX",
            observed_at=NOW - timedelta(minutes=10),
            quantity=0 if buy else 5,
            available_to_sell=0 if buy else 5,
            position_value=0 if buy else 450,
            account_equity=10000,
            available_cash=1000,
            combined_equity=100000,
            combined_symbol_value=0,
            combined_sector_value=0,
            has_open_order=False,
        ),
    )
    plan = TradePlanService(db).generate_trade_plan(request).plan
    return OrderDraftService(db).create_draft(plan.plan_id, as_of=NOW)


def approve(db, draft):
    return (
        OrderDraftService(db)
        .record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=NOW,
        )
        .draft
    )


def reply(status=Status.SUBMITTED, *, fills=(), order_id="SIM-123", response=None):
    return SimulatedReply(
        status=status,
        broker_order_id=order_id,
        fills=fills,
        response=response or {"scenario": "fake"},
    )


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@pytest.mark.parametrize(
    "status", ["pending", "rejected", "no_approval", "stale_approval"]
)
def test_no_submission_without_latest_recorded_approval(database, status):
    db = database
    draft = draft_for(db)
    if status == "rejected":
        OrderDraftService(db).record_decision(
            draft.draft_id, Decision.REJECTED, as_of=NOW
        )
    elif status == "no_approval":
        db.execute(
            "UPDATE order_draft SET status = 'APPROVED' WHERE draft_id = ?",
            [draft.draft_id],
        )
    elif status == "stale_approval":
        approve(db, draft)
        db.execute(
            "INSERT INTO approval_record (approval_id, draft_id, plan_id, decision, decided_at) "
            "VALUES ('newer', ?, ?, 'DEFERRED', ?)",
            [draft.draft_id, draft.plan_id, NOW + timedelta(seconds=1)],
        )
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    with pytest.raises(DraftError):
        SubmissionService(db, adapter, policy=ENABLED).submit_approved_order(
            draft.draft_id, as_of=NOW + timedelta(seconds=2)
        )
    assert not adapter.submissions
    assert count(db, "order_submission_attempt") == 0


@pytest.mark.parametrize("flag,verified", [("false", True), ("true", False)])
def test_switch_and_phase12_gate_default_to_block(database, flag, verified):
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    assert not SubmissionPolicy.from_env({}).enabled
    policy = SubmissionPolicy.from_env(
        {"ORDER_SUBMISSION_ENABLED": flag}, phase12_verified=verified
    )
    with pytest.raises(DraftError) as err:
        SubmissionService(database, adapter, policy=policy).submit_approved_order(
            "unused", as_of=NOW
        )
    assert err.value.code is ErrorType.RISK_RULE_BLOCKED
    assert not adapter.submissions


def test_normal_database_and_unknown_adapter_are_rejected(tmp_path, database):
    path = tmp_path / "normal.duckdb"
    initialize_database(path)
    with connect_database(path) as db:
        with pytest.raises(DraftError, match="模拟"):
            SubmissionService(db, SimulatedSchwabAdapter(), policy=ENABLED)
    with pytest.raises(DraftError, match="模拟"):
        SubmissionService(database, object(), policy=ENABLED)


def test_modification_requires_fresh_approval(database):
    db = database
    draft = approve(db, draft_for(db, buy=True))
    modified = (
        OrderDraftService(db)
        .record_decision(
            draft.draft_id,
            Decision.MODIFIED,
            as_of=NOW,
            replacement=OrderSnapshot.model_validate(
                {**draft.order_snapshot().model_dump(), "quantity": 2}
            ),
        )
        .replacement
    )
    assert (
        modified.status is Status.PENDING_REVIEW
        and modified.replaces_draft_id == draft.draft_id
    )
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    service = SubmissionService(db, adapter, policy=ENABLED)
    for item in (draft, modified):
        with pytest.raises(DraftError):
            service.submit_approved_order(item.draft_id, as_of=NOW)
    approve(db, modified)
    service.submit_approved_order(modified.draft_id, as_of=NOW)
    assert len(adapter.submissions) == 1
    assert adapter.submissions[0].order.quantity == 2


@pytest.mark.parametrize(
    "field,value", [("limit_price", "90.000001"), ("time_in_force", "GTC")]
)
def test_approval_cannot_be_reused_after_immutable_param_changes(
    database, field, value
):
    db = database
    draft = approve(db, draft_for(db))
    db.execute(
        f"UPDATE order_draft SET {field} = ? WHERE draft_id = ?",
        [value, draft.draft_id],
    )
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    with pytest.raises(DraftError, match="快照"):
        SubmissionService(db, adapter, policy=ENABLED).submit_approved_order(
            draft.draft_id, as_of=NOW
        )
    assert not adapter.submissions


@pytest.mark.parametrize("buy", [True, False])
def test_risk_is_rechecked_at_submission(database, buy):
    db = database
    draft = approve(db, draft_for(db, buy=buy))
    if buy:
        db.execute(
            "INSERT INTO portfolio_cash_snapshot (snapshot_id, account_id, snapshot_date, observed_at, "
            "available_to_trade, source) VALUES ('cash', 'SCHWAB_ROTH', ?, ?, 0, 'MANUAL')",
            [DAY, NOW],
        )
    else:
        db.execute(
            "INSERT INTO portfolio_position_snapshot (snapshot_id, account_id, snapshot_date, observed_at, "
            "symbol, quantity) VALUES ('pos', 'SCHWAB_ROTH', ?, ?, 'VRTX', 4)",
            [DAY, NOW],
        )
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    with pytest.raises(DraftError) as err:
        SubmissionService(db, adapter, policy=ENABLED).submit_approved_order(
            draft.draft_id, as_of=NOW
        )
    assert err.value.code is (
        ErrorType.INSUFFICIENT_CASH if buy else ErrorType.INSUFFICIENT_POSITION
    )
    assert not adapter.submissions


def test_attempt_commits_before_adapter_and_accepted_response_is_audited(
    database, monkeypatch
):
    db = database
    draft = approve(db, draft_for(db))
    adapter = SimulatedSchwabAdapter(initial=[reply(response={"mock_receipt": "ACK"})])
    submit = adapter.submit

    def inspect(request):
        assert db.execute(
            "SELECT status FROM order_draft WHERE draft_id = ?", [draft.draft_id]
        ).fetchone() == ("SUBMITTING",)
        assert db.execute("SELECT status FROM order_submission_attempt").fetchone() == (
            "SUBMITTING",
        )
        db.begin()
        db.rollback()
        return submit(request)

    monkeypatch.setattr(adapter, "submit", inspect)
    service = SubmissionService(db, adapter, policy=ENABLED)
    result = service.submit_approved_order(draft.draft_id, as_of=NOW)
    assert result.status is Status.SUBMITTED and result.broker_order_id == "SIM-123"
    assert [
        row[0]
        for row in db.execute(
            "SELECT status FROM order_submission_event ORDER BY event_number"
        ).fetchall()
    ] == ["SUBMITTING", "SUBMITTED"]
    raw = db.execute(
        "SELECT broker_response FROM order_submission_event WHERE status = 'SUBMITTED'"
    ).fetchone()[0]
    assert json.loads(raw)["mock_receipt"] == "ACK"
    assert count(db, "journal_entry") == 3
    assert count(db, "approval_record") == 1
    with pytest.raises(DraftError) as err:
        service.submit_approved_order(draft.draft_id, as_of=NOW)
    assert err.value.code is ErrorType.DUPLICATE_ORDER
    assert len(adapter.submissions) == count(db, "order_submission_attempt") == 1


def test_timeout_and_no_match_do_not_allow_retry(database):
    db = database
    draft = approve(db, draft_for(db))
    adapter = SimulatedSchwabAdapter(
        initial=[TimeoutError("simulated timeout")],
        reconciliations=[
            None,
            reply(Status.FAILED, order_id=None, response={"confirmed": "not accepted"}),
        ],
    )
    service = SubmissionService(db, adapter, policy=ENABLED)
    assert (
        service.submit_approved_order(draft.draft_id, as_of=NOW).status
        is Status.UNKNOWN
    )
    with pytest.raises(DraftError):
        service.submit_approved_order(draft.draft_id, as_of=NOW)
    stopped = SubmissionService(db, adapter)
    assert stopped.reconcile_order(draft.draft_id, as_of=NOW).status is Status.UNKNOWN
    assert stopped.reconcile_order(draft.draft_id, as_of=NOW).status is Status.FAILED
    with pytest.raises(DraftError):
        service.submit_approved_order(draft.draft_id, as_of=NOW)
    assert len(adapter.submissions) == 1 and len(adapter.lookups) == 2


def test_interrupted_submitting_is_reconciled_without_send(database):
    db = database
    draft = approve(db, draft_for(db))
    adapter = SimulatedSchwabAdapter(
        initial=[KeyboardInterrupt()], reconciliations=[reply()]
    )
    service = SubmissionService(db, adapter, policy=ENABLED)
    with pytest.raises(KeyboardInterrupt):
        service.submit_approved_order(draft.draft_id, as_of=NOW)
    assert OrderDraftService(db).get_draft(draft.draft_id).status is Status.SUBMITTING
    with pytest.raises(DraftError):
        service.reconcile_order(draft.draft_id, as_of=NOW)
    assert not adapter.lookups
    result = service.reconcile_order(draft.draft_id, as_of=NOW + timedelta(minutes=3))
    assert result.status is Status.SUBMITTED
    assert len(adapter.submissions) == len(adapter.lookups) == 1


def test_reconciled_partial_fills_are_idempotent_and_canceled_remainder_preserves_them(
    database,
):
    db = database
    draft = approve(db, draft_for(db))
    fill = SimulatedFill(fill_id="fill-1", quantity=2, price=91, executed_at=NOW)
    partial = reply(Status.PARTIALLY_FILLED, fills=[fill])
    adapter = SimulatedSchwabAdapter(
        initial=[TimeoutError()],
        reconciliations=[partial, partial, reply(Status.CANCELED, fills=[fill])],
    )
    service = SubmissionService(db, adapter, policy=ENABLED)
    service.submit_approved_order(draft.draft_id, as_of=NOW)
    for expected in (Status.PARTIALLY_FILLED, Status.PARTIALLY_FILLED, Status.CANCELED):
        assert service.reconcile_order(draft.draft_id, as_of=NOW).status is expected
    assert db.execute(
        "SELECT quantity, price, draft_id FROM broker_transaction"
    ).fetchall() == [(Decimal(2), Decimal(91), draft.draft_id)]
    assert db.execute(
        "SELECT count(*) FROM journal_entry WHERE entry_type = 'TRADE_EXECUTION'"
    ).fetchone() == (1,)
    assert db.execute("SELECT status FROM trade_plan").fetchone() == ("DRAFT",)


def test_reconciliation_refuses_different_broker_order_id(database):
    db = database
    draft = approve(db, draft_for(db))
    adapter = SimulatedSchwabAdapter(
        initial=[reply()],
        reconciliations=[reply(Status.CANCELED, order_id="SIM-other")],
    )
    service = SubmissionService(db, adapter, policy=ENABLED)
    service.submit_approved_order(draft.draft_id, as_of=NOW)
    with pytest.raises(DraftError, match="订单 ID"):
        service.reconcile_order(draft.draft_id, as_of=NOW)
    assert OrderDraftService(db).get_draft(draft.draft_id).broker_order_id == "SIM-123"
    assert count(db, "order_submission_event") == 3
    raw = db.execute(
        "SELECT broker_response FROM order_submission_event ORDER BY event_number DESC LIMIT 1"
    ).fetchone()[0]
    assert json.loads(raw)["unverified_reply"]["broker_order_id"] == "SIM-other"


def test_disabled_account_after_approval_still_blocks_submission(database):
    db = database
    draft = approve(db, draft_for(db))
    db.execute(
        "UPDATE portfolio_account SET is_active = FALSE WHERE account_id = 'SCHWAB_ROTH'"
    )
    adapter = SimulatedSchwabAdapter(initial=[reply()])
    with pytest.raises(DraftError):
        SubmissionService(db, adapter, policy=ENABLED).submit_approved_order(
            draft.draft_id, as_of=NOW
        )
    assert not adapter.submissions and count(db, "order_submission_attempt") == 0


def test_distinct_fills_accumulate_and_inconsistent_fill_rejects_whole_response(
    database,
):
    db = database
    draft = approve(db, draft_for(db))
    first = SimulatedFill(fill_id="f1", quantity=2, price=91, executed_at=NOW)
    too_many = SimulatedFill(fill_id="f2", quantity=4, price=91, executed_at=NOW)
    rest = SimulatedFill(fill_id="f2", quantity=3, price=91, executed_at=NOW)
    adapter = SimulatedSchwabAdapter(
        initial=[reply(Status.PARTIALLY_FILLED, fills=[first])],
        reconciliations=[
            reply(Status.FILLED, fills=[first, too_many]),
            reply(Status.FILLED, fills=[rest]),
        ],
    )
    service = SubmissionService(db, adapter, policy=ENABLED)
    assert (
        service.submit_approved_order(draft.draft_id, as_of=NOW).status
        is Status.PARTIALLY_FILLED
    )
    assert [
        r[0]
        for r in db.execute(
            "SELECT status FROM order_submission_event ORDER BY event_number"
        ).fetchall()
    ] == [
        "SUBMITTING",
        "SUBMITTED",
        "PARTIALLY_FILLED",
    ]
    with pytest.raises(DraftError, match="数量"):
        service.reconcile_order(draft.draft_id, as_of=NOW)
    assert count(db, "broker_transaction") == 1
    assert count(db, "order_submission_event") == 4
    result = service.reconcile_order(draft.draft_id, as_of=NOW)
    assert result.status is Status.FILLED
    assert db.execute(
        "SELECT count(*), sum(quantity) FROM broker_transaction"
    ).fetchone() == (2, Decimal(5))


@pytest.mark.parametrize("after_send", [False, True])
def test_audit_write_failure_never_allows_second_send(
    database, monkeypatch, after_send
):
    from broker_gateway.submission import _repository

    db = database
    draft = approve(db, draft_for(db))
    original = _repository.insert_journal_entry

    def fail(db, entry):
        if ("SUBMITTED" if after_send else "SUBMITTING") in entry.system_note:
            raise RuntimeError("simulated audit error")
        return original(db, entry)

    adapter = SimulatedSchwabAdapter(initial=[reply()], reconciliations=[reply()])
    service = SubmissionService(db, adapter, policy=ENABLED)
    with monkeypatch.context() as patch:
        patch.setattr(_repository, "insert_journal_entry", fail)
        with pytest.raises(RuntimeError, match="audit error"):
            service.submit_approved_order(draft.draft_id, as_of=NOW)
    current = OrderDraftService(db).get_draft(draft.draft_id)
    assert (
        len(adapter.submissions)
        == count(db, "order_submission_attempt")
        == int(after_send)
    )
    assert current.status is (Status.SUBMITTING if after_send else Status.APPROVED)
    if after_send:
        with pytest.raises(DraftError):
            service.submit_approved_order(draft.draft_id, as_of=NOW)
        assert (
            service.reconcile_order(
                draft.draft_id, as_of=NOW + timedelta(minutes=3)
            ).status
            is Status.SUBMITTED
        )
        assert len(adapter.submissions) == 1


def test_invalid_initial_receipt_is_retained_but_does_not_claim_a_fill(database):
    db = database
    draft = approve(db, draft_for(db))
    adapter = SimulatedSchwabAdapter(initial=[reply(Status.FILLED)])
    attempt = SubmissionService(db, adapter, policy=ENABLED).submit_approved_order(
        draft.draft_id, as_of=NOW
    )
    assert attempt.status is Status.UNKNOWN and attempt.broker_order_id is None
    assert count(db, "broker_transaction") == 0
    raw = db.execute(
        "SELECT broker_response FROM order_submission_event WHERE status = 'UNKNOWN'"
    ).fetchone()[0]
    assert json.loads(raw)["unverified_reply"]["status"] == "FILLED"
