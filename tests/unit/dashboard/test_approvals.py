from datetime import UTC, date, datetime, timedelta

import pytest

from apps.dashboard_approvals import DashboardApprovalService
from broker_gateway.drafts import DraftError, OrderDraftService
from investment_journal.services.journal_service import JournalService
from shared.db import connect_database, get_journal_entry, initialize_database
from shared.enums import ApprovalDecision as Decision
from shared.enums import ErrorType, OrderDraftStatus
from trade_planner.planners.base import PlanningRequest, PortfolioState
from trade_planner.services.trade_plan_service import TradePlanService

NOW = datetime(2026, 6, 9, 1, 5, tzinfo=UTC)
DAY = date(2026, 6, 8)


@pytest.fixture
def order(tmp_path):
    path = tmp_path / "dashboard.duckdb"
    initialize_database(path)
    with connect_database(path) as db:
        sessions = (date(2026, 6, 5), DAY)
        for day in sessions:
            db.execute(
                "INSERT INTO daily_price (symbol, trade_date, close) VALUES ('VRTX', ?, 90)",
                [day],
            )
            db.execute(
                "INSERT INTO daily_indicator (symbol, trade_date, ma200) VALUES ('VRTX', ?, 100)",
                [day],
            )
        db.execute(
            "INSERT INTO daily_signal (signal_id, symbol, trade_date, confidence) VALUES ('signal', 'VRTX', ?, 5)",
            [DAY],
        )
        issued = NOW - timedelta(minutes=5)
        plan = (
            TradePlanService(db)
            .generate_trade_plan(
                PlanningRequest(
                    account_id="SCHWAB_ROTH",
                    signal_id="signal",
                    as_of=issued,
                    trading_sessions=sessions,
                    exit_limit_price=90,
                    portfolio=PortfolioState(
                        account_id="SCHWAB_ROTH",
                        symbol="VRTX",
                        observed_at=issued,
                        quantity=5,
                        available_to_sell=5,
                        position_value=450,
                        has_open_order=False,
                    ),
                )
            )
            .plan
        )
        draft = OrderDraftService(db).create_draft(plan.plan_id, as_of=issued)
        yield db, draft


@pytest.mark.parametrize(
    "decision", [Decision.APPROVED, Decision.REJECTED, Decision.DEFERRED]
)
def test_local_decisions_write_draft_approval_and_linked_chicago_journal(
    order, decision
):
    db, draft = order
    result = DashboardApprovalService(db).decide(
        draft, decision, note="人工复核", as_of=NOW
    )
    saved = OrderDraftService(db).get_approval(result.approval.approval_id)
    assert saved == result.approval
    assert result.draft.status == OrderDraftStatus(decision.value)
    assert result.draft.broker_order_id is None
    assert saved.approved_payload == (
        draft.order_snapshot() if decision is Decision.APPROVED else None
    )
    journal_id = f"JRN-APPROVAL-{saved.approval_id}"
    entry = get_journal_entry(db, journal_id)
    assert entry.journal_date == DAY
    assert (entry.draft_id, entry.plan_id, entry.account_id, entry.symbol) == (
        draft.draft_id,
        draft.plan_id,
        draft.account_id,
        draft.symbol,
    )
    assert entry.decision_reason == "人工复核"
    assert entry.system_note == f"审批结果 {decision.value}"
    JournalService(db).record_approval(saved)
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (1,)


def test_journal_failure_rolls_back_approval_and_status(order, monkeypatch):
    db, draft = order

    def fail(*args, **kwargs):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(JournalService, "record_approval", fail)
    with pytest.raises(RuntimeError, match="journal unavailable"):
        DashboardApprovalService(db).decide(draft, Decision.APPROVED, as_of=NOW)
    assert OrderDraftService(db).get_draft(draft.draft_id) == draft
    assert db.execute("SELECT count(*) FROM approval_record").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (0,)


def test_reviewed_snapshot_and_revision_are_required_even_for_rejection(order):
    db, draft = order
    db.execute(
        "UPDATE order_draft SET quantity = 4 WHERE draft_id = ?", [draft.draft_id]
    )
    service = DashboardApprovalService(db)
    with pytest.raises(DraftError, match="重新审阅"):
        service.decide(draft, Decision.REJECTED, as_of=NOW)
    assert db.execute("SELECT count(*) FROM approval_record").fetchone() == (0,)


def test_deferred_remains_non_approvable_until_explicit_reopen(order):
    db, draft = order
    service = DashboardApprovalService(db)
    deferred = service.decide(draft, Decision.DEFERRED, as_of=NOW).draft
    with pytest.raises(DraftError):
        service.decide(deferred, Decision.APPROVED, as_of=NOW + timedelta(minutes=1))
    reopened = service.reopen(deferred, as_of=NOW + timedelta(minutes=1))
    assert reopened.status is OrderDraftStatus.PENDING_REVIEW
    with pytest.raises(DraftError, match="重新审阅"):
        service.decide(draft, Decision.APPROVED, as_of=NOW + timedelta(minutes=2))
    renewed = service.decide(
        reopened, Decision.APPROVED, as_of=NOW + timedelta(minutes=2)
    )
    assert renewed.draft.status is OrderDraftStatus.APPROVED
    assert db.execute("SELECT count(*) FROM approval_record").fetchone() == (2,)


def test_local_approval_revalidates_positions_and_cannot_be_replayed(order):
    db, draft = order
    service = DashboardApprovalService(db)
    db.execute(
        "INSERT INTO portfolio_position_snapshot (snapshot_id, account_id, symbol, snapshot_date, "
        "observed_at, quantity) VALUES ('latest', 'SCHWAB_ROTH', 'VRTX', ?, ?, 0)",
        [DAY, NOW],
    )
    with pytest.raises(DraftError) as err:
        service.decide(draft, Decision.APPROVED, as_of=NOW)
    assert err.value.code is ErrorType.INSUFFICIENT_POSITION
    service.decide(draft, Decision.REJECTED, as_of=NOW)
    with pytest.raises(DraftError):
        service.decide(draft, Decision.REJECTED, as_of=NOW)
    assert db.execute("SELECT count(*) FROM approval_record").fetchone() == (1,)
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (1,)


@pytest.mark.parametrize("restriction", ["broker", "policy"])
def test_local_configuration_can_disable_approval_but_not_rejection(
    order, tmp_path, restriction
):
    db, draft = order
    config = tmp_path / "config"
    config.mkdir()
    (config / "risk.yaml").write_text("risk: {}\n", encoding="utf-8")
    (config / "accounts.yaml").write_text(
        "accounts:\n  SCHWAB_ROTH:\n    broker: SCHWAB\n    account_role: ACTIVE_TRADING\n"
        f"    individual_stock_policy: {'EXIT_ONLY' if restriction == 'policy' else 'ACTIVE_ALLOWED'}\n"
        "    order_draft_enabled: true\n",
        encoding="utf-8",
    )
    (config / "broker.yaml").write_text(
        "brokers:\n  schwab:\n    enabled: true\n"
        f"    order_draft_enabled: {'false' if restriction == 'broker' else 'true'}\n",
        encoding="utf-8",
    )
    service = DashboardApprovalService(db, config_dir=config)
    with pytest.raises(DraftError, match="配置"):
        service.decide(draft, Decision.APPROVED, as_of=NOW)
    result = service.decide(draft, Decision.REJECTED, as_of=NOW)
    assert result.draft.status is OrderDraftStatus.REJECTED
