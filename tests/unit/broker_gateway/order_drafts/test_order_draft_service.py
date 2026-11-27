import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from broker_gateway.drafts import DraftError, OrderDraftService
from shared.db import connect_database, initialize_database, insert_trade_plan
from shared.enums import Action, Broker, ErrorType, OrderDraftStatus, OrderInstruction
from shared.enums import ApprovalDecision as Decision
from shared.models import IntradaySignal, OrderSnapshot, TradePlan
from trade_planner.planners.base import EntryPrices, PlanningRequest, PortfolioState
from trade_planner.services.trade_plan_service import TradePlanService

DAY = date(2026, 6, 8)
SESSIONS = (
    date(2026, 6, 4),
    date(2026, 6, 5),
    DAY,
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
    date(2026, 6, 12),
    date(2026, 6, 15),
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "orders.duckdb"
    initialize_database(path)
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO daily_signal (signal_id, symbol, trade_date, false_breakdown_score, "
            "volume_confirmation_score, market_regime, confidence) "
            "VALUES ('SIG-1', 'VRTX', ?, 100, 100, 'RANGE', 85)",
            [SESSIONS[1]],
        )
        yield connection


@pytest.fixture
def request_data():
    return PlanningRequest(
        account_id="SCHWAB_ROTH",
        signal_id="SIG-1",
        reentry_candidate=True,
        as_of="2026-06-08T16:00:00Z",
        trading_sessions=SESSIONS,
        earnings_checked_through=SESSIONS[-1],
        entry_prices=EntryPrices(limit_price=100, stop_price=95, target_price=115),
        exit_limit_price=99,
        portfolio=PortfolioState(
            account_id="SCHWAB_ROTH",
            symbol="VRTX",
            observed_at="2026-06-08T15:55:00Z",
            account_equity=10000,
            available_cash=1000,
            quantity=0,
            position_value=0,
            available_to_sell=0,
            has_open_order=False,
            combined_equity=100000,
            combined_symbol_value=0,
            combined_sector_value=5000,
        ),
        intraday_signal=IntradaySignal(
            signal_id="HOUR-1",
            symbol="VRTX",
            trade_date=DAY,
            bar_start="2026-06-08T14:30:00Z",
            hourly_trend="HIGHER_LOW_CONFIRMED",
            vwap_status="ABOVE_VWAP",
        ),
    )


def plan_for(db, request):
    return TradePlanService(db).generate_trade_plan(request).plan


def held(request, quantity=5, value=450):
    return request.model_copy(
        update={
            "intraday_signal": None,
            "portfolio": PortfolioState.model_validate(
                {
                    **request.portfolio.model_dump(),
                    "quantity": quantity,
                    "position_value": value,
                    "available_to_sell": quantity,
                }
            ),
        }
    )


def two_closes(db):
    for day in SESSIONS[:2]:
        db.execute(
            "INSERT INTO daily_price (symbol, trade_date, close) VALUES ('VRTX', ?, 90)",
            [day],
        )
        db.execute(
            "INSERT INTO daily_indicator (symbol, trade_date, ma200) VALUES ('VRTX', ?, 100)",
            [day],
        )


def cash(db, observed_at, value):
    db.execute(
        "INSERT INTO portfolio_cash_snapshot (snapshot_id, account_id, snapshot_date, observed_at, "
        "currency, available_to_trade, source) VALUES ('cash', 'SCHWAB_ROTH', ?, ?, 'USD', ?, 'CSV')",
        [DAY, observed_at, value],
    )


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def draft_for(db, request):
    service = OrderDraftService(db)
    plan = plan_for(db, request)
    return service, service.create_draft(plan.plan_id, as_of=request.as_of)


def test_planner_to_draft_to_explicit_approval(db, request_data):
    service, draft = draft_for(db, request_data)
    assert draft.status is OrderDraftStatus.PENDING_REVIEW
    assert draft.broker is Broker.SCHWAB and draft.instruction is OrderInstruction.BUY
    assert draft.quantity == 3 and draft.limit_price == 100
    assert draft.stop_price is None and draft.raw_payload is None
    assert service.get_draft(draft.draft_id) == draft
    assert count(db, "approval_record") == 0
    for reviewed in (
        None,
        OrderSnapshot.model_validate(
            {**draft.order_snapshot().model_dump(), "quantity": 2}
        ),
    ):
        with pytest.raises(DraftError):
            service.record_decision(
                draft.draft_id,
                Decision.APPROVED,
                reviewed_payload=reviewed,
                as_of=request_data.as_of,
            )
    assert service.get_draft(draft.draft_id).status is OrderDraftStatus.PENDING_REVIEW
    result = service.record_decision(
        draft.draft_id,
        Decision.APPROVED,
        reviewed_payload=draft.order_snapshot(),
        decision_note="看过账户和价格",
        as_of=request_data.as_of,
    )
    assert result.draft.status is OrderDraftStatus.APPROVED
    assert result.approval.approved_payload == draft.order_snapshot()
    assert service.get_approval(result.approval.approval_id) == result.approval
    assert count(db, "approval_record") == 1
    assert db.execute(
        "SELECT status FROM trade_plan WHERE plan_id = ?", [draft.plan_id]
    ).fetchone() == ("DRAFT",)


@pytest.mark.parametrize(
    "action", [Action.WATCH, Action.HOLD, Action.AVOID, Action.EXIT_ONLY]
)
def test_non_actionable_plan_cannot_create_draft(db, request_data, action):
    plan = plan_for(db, request_data)
    db.execute(
        "UPDATE trade_plan SET action = ?, exit_trigger = '[\"conditional\"]' WHERE plan_id = ?",
        [action.value, plan.plan_id],
    )
    with pytest.raises(DraftError):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)
    assert count(db, "order_draft") == 0


@pytest.mark.parametrize("action", [Action.ADD, Action.RE_ENTRY])
def test_low_confidence_never_passes_entry_gate(db, request_data, action):
    plan = plan_for(db, request_data)
    db.execute(
        "UPDATE trade_plan SET confidence = 69, action = ? WHERE plan_id = ?",
        [action.value, plan.plan_id],
    )
    with pytest.raises(DraftError, match="置信度"):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)


@pytest.mark.parametrize(
    "case", ["missing", "stale", "unsatisfied", "not_closed", "mismatch"]
)
def test_hourly_evidence_revalidated_by_gateway(db, request_data, case):
    plan = plan_for(db, request_data)
    references = plan.input_references
    if case == "missing":
        references.pop("intraday_signal")
    elif case == "unsatisfied":
        references["intraday_signal"]["vwap_status"] = "BELOW_VWAP"
    elif case == "not_closed":
        references["intraday_signal"]["bar_start"] = "2026-06-08T15:30:00Z"
    elif case == "mismatch":
        references["intraday_signal"]["signal_id"] = "OTHER"
    db.execute(
        "UPDATE trade_plan SET input_references = ? WHERE plan_id = ?",
        [json.dumps(references), plan.plan_id],
    )
    at = (
        request_data.as_of + timedelta(hours=3)
        if case == "stale"
        else request_data.as_of
    )
    with pytest.raises(DraftError, match="小时"):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=at)


def test_individual_vanguard_buy_blocked_even_if_account_drafts_enabled(
    db, request_data
):
    plan = plan_for(db, request_data)
    db.execute(
        "UPDATE portfolio_account SET order_draft_enabled = TRUE WHERE account_id = 'VANGUARD_ROTH'"
    )
    vanguard = TradePlan.model_validate(
        {
            **plan.model_dump(),
            "plan_id": "VANGUARD-BUY",
            "account_id": "VANGUARD_ROTH",
            "account_role": "CORE_PASSIVE",
        }
    )
    insert_trade_plan(db, vanguard)
    with pytest.raises(DraftError, match="个股买入"):
        OrderDraftService(db).create_draft(vanguard.plan_id, as_of=request_data.as_of)


@pytest.mark.parametrize(
    ("action", "quantity", "value", "order_qty"),
    [
        (Action.EXIT, 5, 450, Decimal(5)),
        (Action.REDUCE, 10, 1000, Decimal(2)),
    ],
)
def test_protective_exit_is_independent_of_entry_threshold(
    db, request_data, action, quantity, value, order_qty
):
    if action is Action.EXIT:
        two_closes(db)
    request = held(request_data, quantity, value)
    plan = plan_for(db, request)
    assert plan.action is action
    db.execute("UPDATE trade_plan SET confidence = 5 WHERE plan_id = ?", [plan.plan_id])
    draft = OrderDraftService(db).create_draft(plan.plan_id, as_of=request.as_of)
    assert draft.instruction is OrderInstruction.SELL and draft.quantity == order_qty


def test_protective_label_alone_does_not_allow_sell(db, request_data):
    plan = plan_for(db, held(request_data, 10, 1000))
    db.execute(
        "UPDATE trade_plan SET action = 'EXIT', exit_trigger = '[\"two_completed_closes_below_ma200\"]' WHERE plan_id = ?",
        [plan.plan_id],
    )
    with pytest.raises(DraftError, match="MA200"):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)


def test_corrected_close_breaks_previously_valid_exit(db, request_data):
    two_closes(db)
    plan = plan_for(db, held(request_data))
    db.execute("UPDATE daily_price SET close = 101 WHERE trade_date = ?", [SESSIONS[1]])
    with pytest.raises(DraftError, match="MA200"):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)


def test_duplicate_and_stale_plan_do_not_create_second_draft(db, request_data):
    service, draft = draft_for(db, request_data)
    with pytest.raises(DraftError) as err:
        service.create_draft(draft.plan_id, as_of=request_data.as_of)
    assert err.value.code is ErrorType.DUPLICATE_ORDER
    newer = plan_for(db, request_data.model_copy(update={"intraday_signal": None}))
    assert newer.supersedes_plan_id == draft.plan_id
    with pytest.raises(DraftError, match="替代"):
        service.record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=request_data.as_of,
        )
    assert count(db, "order_draft") == 1 and count(db, "approval_record") == 0


def test_latest_cash_checks_before_drafting_and_approval(db, request_data):
    plan = plan_for(db, request_data)
    service = OrderDraftService(db)
    cash(db, request_data.as_of, 299)
    with pytest.raises(DraftError) as err:
        service.create_draft(plan.plan_id, as_of=request_data.as_of)
    assert err.value.code is ErrorType.INSUFFICIENT_CASH
    db.execute("UPDATE portfolio_cash_snapshot SET available_to_trade = 300")
    draft = service.create_draft(plan.plan_id, as_of=request_data.as_of)
    db.execute("UPDATE portfolio_cash_snapshot SET available_to_trade = 0")
    with pytest.raises(DraftError) as err:
        service.record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=request_data.as_of,
        )
    assert err.value.code is ErrorType.INSUFFICIENT_CASH
    assert count(db, "approval_record") == 0


def test_new_holding_snapshot_blocks_oversized_sell(db, request_data):
    two_closes(db)
    plan = plan_for(db, held(request_data))
    db.execute(
        "INSERT INTO portfolio_position_snapshot (snapshot_id, account_id, snapshot_date, observed_at, "
        "symbol, quantity, source) VALUES ('POS', 'SCHWAB_ROTH', ?, ?, 'VRTX', 4, 'CSV')",
        [DAY, request_data.as_of],
    )
    with pytest.raises(DraftError) as err:
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)
    assert err.value.code is ErrorType.INSUFFICIENT_POSITION


def test_new_earnings_block_after_plan_was_generated(db, request_data):
    plan = plan_for(db, request_data)
    db.execute(
        "INSERT INTO corporate_event (event_id, symbol, event_type, event_date) VALUES ('E', 'VRTX', 'EARNINGS', ?)",
        [SESSIONS[-1]],
    )
    with pytest.raises(DraftError, match="财报"):
        OrderDraftService(db).create_draft(plan.plan_id, as_of=request_data.as_of)


def test_modification_creates_new_draft_and_requires_fresh_approval(db, request_data):
    service, draft = draft_for(db, request_data)
    approved = service.record_decision(
        draft.draft_id,
        Decision.APPROVED,
        reviewed_payload=draft.order_snapshot(),
        as_of=request_data.as_of,
    )
    snapshot = OrderSnapshot.model_validate(
        {**draft.order_snapshot().model_dump(), "quantity": 2}
    )
    result = service.record_decision(
        draft.draft_id,
        Decision.MODIFIED,
        replacement=snapshot,
        as_of=request_data.as_of,
    )
    new = result.replacement
    assert result.draft.status is OrderDraftStatus.MODIFIED
    assert new.draft_id != draft.draft_id and new.replaces_draft_id == draft.draft_id
    assert new.status is OrderDraftStatus.PENDING_REVIEW
    assert approved.approval.approved_payload != new.order_snapshot()
    with pytest.raises(DraftError):
        service.record_decision(
            new.draft_id,
            Decision.APPROVED,
            reviewed_payload=approved.approval.approved_payload,
            as_of=request_data.as_of,
        )
    assert count(db, "approval_record") == 2
    assert (
        service.record_decision(
            new.draft_id,
            Decision.APPROVED,
            reviewed_payload=new.order_snapshot(),
            as_of=request_data.as_of,
        ).draft.status
        is OrderDraftStatus.APPROVED
    )


def test_modification_cannot_change_side_or_increase_risk(db, request_data):
    service, draft = draft_for(db, request_data)
    for changes in ({"instruction": "SELL"}, {"quantity": 4}, {"limit_price": 101}):
        snapshot = OrderSnapshot.model_validate(
            {**draft.order_snapshot().model_dump(), **changes}
        )
        with pytest.raises(DraftError):
            service.record_decision(
                draft.draft_id,
                Decision.MODIFIED,
                replacement=snapshot,
                as_of=request_data.as_of,
            )
    assert count(db, "order_draft") == 1 and count(db, "approval_record") == 0


def test_cash_balance_is_not_tradable_cash(db, request_data):
    plan = plan_for(db, request_data)
    cash(db, request_data.as_of, None)
    db.execute("UPDATE portfolio_cash_snapshot SET cash_balance = 1000")
    service = OrderDraftService(db)
    draft = service.create_draft(plan.plan_id, as_of=request_data.as_of)
    assert draft.status is OrderDraftStatus.PENDING_REVIEW
    with pytest.raises(DraftError) as err:
        service.record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=request_data.as_of,
        )
    assert err.value.code is ErrorType.DATA_MISSING
    assert count(db, "approval_record") == 0


def test_local_approval_requires_a_persisted_exact_match_and_current_evidence(
    db, request_data
):
    service, draft = draft_for(db, request_data)
    db.execute(
        "UPDATE order_draft SET status = 'APPROVED' WHERE draft_id = ?",
        [draft.draft_id],
    )
    with pytest.raises(DraftError) as err:
        service.require_current_approval(draft.draft_id, as_of=request_data.as_of)
    assert err.value.code is ErrorType.USER_APPROVAL_REQUIRED
    db.execute(
        "UPDATE order_draft SET status = 'PENDING_REVIEW' WHERE draft_id = ?",
        [draft.draft_id],
    )
    approved = service.record_decision(
        draft.draft_id,
        Decision.APPROVED,
        reviewed_payload=draft.order_snapshot(),
        as_of=request_data.as_of,
    )
    assert (
        service.require_current_approval(draft.draft_id, as_of=request_data.as_of)
        == approved.approval
    )
    with pytest.raises(DraftError, match="小时"):
        service.require_current_approval(
            draft.draft_id, as_of=request_data.as_of + timedelta(hours=3)
        )
    db.execute(
        "UPDATE order_draft SET quantity = 1 WHERE draft_id = ?", [draft.draft_id]
    )
    with pytest.raises(DraftError, match="快照"):
        service.require_current_approval(draft.draft_id, as_of=request_data.as_of)


def test_newer_daily_revision_blocks_even_before_a_replacement_plan(db, request_data):
    service, draft = draft_for(db, request_data)
    db.execute(
        "INSERT INTO daily_signal (signal_id, symbol, trade_date, market_regime, confidence, created_at) "
        "SELECT 'CORRECTED', symbol, trade_date, 'HIGH_RISK', 10, created_at + INTERVAL '1 second' "
        "FROM daily_signal WHERE signal_id = 'SIG-1'"
    )
    with pytest.raises(DraftError, match="日线"):
        service.record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=request_data.as_of,
        )
    assert count(db, "approval_record") == 0


def test_deferred_needs_reopening_and_rejected_is_not_approvable(db, request_data):
    service, draft = draft_for(db, request_data)

    def record(decision, **kwargs):
        return service.record_decision(
            draft.draft_id, decision, as_of=request_data.as_of, **kwargs
        )

    assert record(Decision.DEFERRED).draft.status is OrderDraftStatus.DEFERRED
    with pytest.raises(DraftError):
        record(Decision.APPROVED, reviewed_payload=draft.order_snapshot())
    assert (
        service.reopen_deferred(draft.draft_id, as_of=request_data.as_of).status
        is OrderDraftStatus.PENDING_REVIEW
    )
    assert record(Decision.REJECTED).draft.status is OrderDraftStatus.REJECTED
    with pytest.raises(DraftError):
        record(Decision.APPROVED, reviewed_payload=draft.order_snapshot())
    assert count(db, "approval_record") == 2


def test_approval_write_failure_rolls_back_draft_transition(
    db, request_data, monkeypatch
):
    service, draft = draft_for(db, request_data)
    original = service._insert

    def fail(table, model):
        if table == "approval_record":
            raise ValueError("test failure")
        original(table, model)

    monkeypatch.setattr(service, "_insert", fail)
    with pytest.raises(DraftError):
        service.record_decision(
            draft.draft_id,
            Decision.APPROVED,
            reviewed_payload=draft.order_snapshot(),
            as_of=request_data.as_of,
        )
    assert count(db, "approval_record") == 0
    assert service.get_draft(draft.draft_id).status is OrderDraftStatus.PENDING_REVIEW
