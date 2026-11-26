from datetime import date, timedelta
from decimal import Decimal

import pytest

from shared.db import connect_database, get_trade_plan, initialize_database
from shared.enums import Action, OrderInstruction, TradePlanStatus
from shared.models import IntradaySignal
from trade_planner.planners.base import EntryPrices, PlanningRequest, PortfolioState
from trade_planner.services.trade_plan_service import TradePlanService

LAST = date(2026, 6, 5)
EXECUTION = date(2026, 6, 8)
EARNINGS_BOUNDARY = date(2026, 6, 15)
SESSIONS = (
    date(2026, 6, 4),
    LAST,
    EXECUTION,
    date(2026, 6, 9),
    date(2026, 6, 10),
    date(2026, 6, 11),
    date(2026, 6, 12),
    EARNINGS_BOUNDARY,
    date(2026, 6, 16),
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "plans.duckdb"
    initialize_database(path)
    with connect_database(path) as connection:
        connection.execute(
            """
            INSERT INTO daily_signal (
                signal_id, symbol, trade_date, false_breakdown_score,
                volume_confirmation_score, market_regime, confidence
            ) VALUES ('SIG-1', 'VRTX', ?, 100, 100, 'RANGE', 85)
            """,
            [LAST],
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
        earnings_checked_through=EARNINGS_BOUNDARY,
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
            signal_id="ISIG-1",
            symbol="VRTX",
            trade_date=EXECUTION,
            bar_start="2026-06-08T14:30:00Z",
            hourly_trend="HIGHER_LOW_CONFIRMED",
            vwap_status="ABOVE_VWAP",
        ),
    )


def portfolio_with(request, **changes):
    return PortfolioState.model_validate({**request.portfolio.model_dump(), **changes})


@pytest.mark.parametrize(
    "quantity, action", [(0, Action.AVOID), (10, Action.EXIT_ONLY)]
)
def test_vanguard_has_no_individual_stock_buy_intent(
    db, request_data, quantity, action
):
    request = request_data.model_copy(
        update={
            "account_id": "VANGUARD_ROTH",
            "portfolio": portfolio_with(
                request_data,
                account_id="VANGUARD_ROTH",
                quantity=quantity,
                position_value=quantity * 100,
                available_to_sell=quantity,
            ),
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.action is action
    assert result.order_intent is None
    assert result.plan.invalid_condition
    assert result.plan.replacement is None
    if quantity:
        assert result.plan.exit_trigger
        assert result.plan.future_reentry_account == "SCHWAB_ROTH"


def test_vanguard_uses_only_explicit_replacement_config(db, request_data):
    db.execute(
        """UPDATE portfolio_account SET default_replacement = '{"VOO":0.6,"QQQ":0.4}'
        WHERE account_id = 'VANGUARD_ROTH'"""
    )
    request = request_data.model_copy(
        update={
            "account_id": "VANGUARD_ROTH",
            "portfolio": portfolio_with(
                request_data,
                account_id="VANGUARD_ROTH",
                quantity=10,
                position_value=1000,
                available_to_sell=10,
            ),
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.replacement == {"VOO": 0.6, "QQQ": 0.4}
    assert result.order_intent is None


def test_high_confidence_reentry_uses_account_sizing_and_persists_signal_link(
    db, request_data
):
    service = TradePlanService(db)
    result = service.generate_trade_plan(request_data)
    assert result.plan.action is Action.RE_ENTRY
    assert result.plan.status is TradePlanStatus.DRAFT
    assert result.plan.position_size.sizing_base_value == Decimal(10000)
    assert result.plan.position_size.estimated_value == Decimal(300)
    assert result.plan.position_size.percent_of_portfolio == 3
    assert result.plan.position_size.quantity == Decimal(3)
    assert result.plan.invalid_condition
    assert result.order_intent.instruction is OrderInstruction.BUY
    assert result.order_intent.limit_price == Decimal(100)
    assert get_trade_plan(db, result.plan.plan_id) == result.plan
    assert db.execute(
        "SELECT signal_id FROM trade_plan_signal_link WHERE plan_id = ?",
        [result.plan.plan_id],
    ).fetchone() == ("SIG-1",)
    assert service.generate_trade_plan(request_data).plan == result.plan


@pytest.mark.parametrize("confidence", [0, 49, 69])
def test_entry_confidence_below_threshold_cannot_make_an_actionable_plan(
    db, request_data, confidence
):
    db.execute("UPDATE daily_signal SET confidence = ?", [confidence])
    result = TradePlanService(db).generate_trade_plan(request_data)
    assert result.plan.action is Action.WATCH
    assert result.order_intent is None
    assert result.plan.invalid_condition


@pytest.mark.parametrize(
    "hourly",
    [
        None,
        {"bar_start": "2026-06-08T12:30:00Z"},
        {"bar_start": "2026-06-08T15:30:00Z"},
        {"hourly_trend": "HIGHER_LOW_FORMING"},
        {"vwap_status": "BELOW_VWAP"},
        {"symbol": "QQQ"},
    ],
)
def test_hourly_confirmation_is_a_separate_entry_gate(db, request_data, hourly):
    db.execute("UPDATE daily_signal SET confidence = 70")
    signal = (
        None
        if hourly is None
        else IntradaySignal.model_validate(
            {**request_data.intraday_signal.model_dump(), **hourly}
        )
    )
    result = TradePlanService(db).generate_trade_plan(
        request_data.model_copy(update={"intraday_signal": signal})
    )
    assert result.plan.action is Action.WATCH
    assert result.order_intent is None


def test_earnings_window_includes_fifth_session_and_requires_coverage(db, request_data):
    db.execute(
        "INSERT INTO corporate_event (event_id, symbol, event_date, event_type) "
        "VALUES ('ER-1', 'VRTX', ?, 'EARNINGS')",
        [EARNINGS_BOUNDARY],
    )
    service = TradePlanService(db)
    blocked = service.generate_trade_plan(request_data)
    assert blocked.plan.action is Action.WATCH
    assert blocked.order_intent is None

    db.execute("UPDATE corporate_event SET event_date = ?", [date(2026, 6, 16)])
    open_ = service.generate_trade_plan(request_data)
    assert open_.plan.action is Action.RE_ENTRY
    assert open_.plan.supersedes_plan_id == blocked.plan.plan_id
    pending = service.generate_trade_plan(
        request_data.model_copy(update={"earnings_checked_through": None})
    )
    assert pending.plan.action is Action.WATCH
    assert pending.order_intent is None


@pytest.mark.parametrize(
    "exposure",
    [
        {"combined_symbol_value": 8000},
        {"combined_sector_value": 25000},
        {"combined_equity": None},
        {"available_cash": 0},
        {"has_open_order": True},
    ],
)
def test_cash_and_combined_exposures_are_independent_gates(db, request_data, exposure):
    result = TradePlanService(db).generate_trade_plan(
        request_data.model_copy(
            update={"portfolio": portfolio_with(request_data, **exposure)}
        )
    )
    assert result.plan.action is Action.WATCH
    assert result.order_intent is None


def test_existing_position_can_get_add_plan(db, request_data):
    request = request_data.model_copy(
        update={
            "portfolio": portfolio_with(
                request_data,
                quantity=4,
                available_to_sell=4,
                position_value=400,
                combined_symbol_value=400,
            )
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.action is Action.ADD


@pytest.mark.parametrize(
    ("scores", "confidence", "expected"),
    [
        ((100, 80), None, Action.RE_ENTRY),
        ((100, 66), None, Action.WATCH),
        ((100, None), None, Action.WATCH),
        ((100, 66), 80, Action.RE_ENTRY),
        ((60, 100), 100, Action.WATCH),
    ],
)
def test_phase4_scores_can_fill_missing_confidence_but_remain_separate_gates(
    db, request_data, scores, confidence, expected
):
    db.execute(
        "UPDATE daily_signal SET false_breakdown_score = ?, "
        "volume_confirmation_score = ?, confidence = ?",
        [*scores, confidence],
    )
    result = TradePlanService(db).generate_trade_plan(request_data)
    assert result.plan.action is expected
    assert (result.order_intent is not None) == (expected is Action.RE_ENTRY)
    assert result.plan.confidence == (
        confidence
        if confidence is not None
        else min(scores) if None not in scores else None
    )


def test_entry_needs_an_actual_reentry_candidate_and_valid_price_setup(
    db, request_data
):
    service = TradePlanService(db)
    for change in (
        {"reentry_candidate": False},
        {"entry_prices": None},
        {"entry_prices": EntryPrices(limit_price=100, stop_price=95, target_price=109)},
        {"entry_prices": EntryPrices(limit_price=100, stop_price=49, target_price=210)},
    ):
        result = service.generate_trade_plan(request_data.model_copy(update=change))
        assert result.plan.action is Action.WATCH
        assert result.order_intent is None


def test_protective_exit_ignores_entry_confidence_and_hourly_and_earnings_gates(
    db, request_data
):
    db.execute("UPDATE daily_signal SET confidence = 5")
    for day in SESSIONS[:2]:
        db.execute(
            "INSERT INTO daily_price (symbol, trade_date, close) VALUES ('VRTX', ?, 90)",
            [day],
        )
        db.execute(
            "INSERT INTO daily_indicator (symbol, trade_date, ma200) VALUES ('VRTX', ?, 100)",
            [day],
        )
    request = request_data.model_copy(
        update={
            "intraday_signal": None,
            "earnings_checked_through": None,
            "portfolio": portfolio_with(
                request_data, quantity=5, available_to_sell=5, position_value=450
            ),
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.action is Action.EXIT
    assert result.plan.position_size.quantity == Decimal(5)
    assert result.plan.invalid_condition
    assert result.order_intent.instruction is OrderInstruction.SELL


def test_protective_review_without_limit_has_no_order_intent(db, request_data):
    request = request_data.model_copy(
        update={
            "exit_limit_price": None,
            "portfolio": portfolio_with(
                request_data,
                quantity=10,
                available_to_sell=10,
                position_value=1000,
            ),
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.action is Action.REDUCE
    assert result.plan.position_size.quantity == Decimal(2)
    assert result.order_intent is None


def test_existing_reviewed_plan_is_preserved_on_changed_inputs(db, request_data):
    service = TradePlanService(db)
    first = service.generate_trade_plan(request_data).plan
    db.execute(
        "UPDATE trade_plan SET status = 'REVIEWED' WHERE plan_id = ?", [first.plan_id]
    )
    assert (
        service.generate_trade_plan(request_data).plan.status
        is TradePlanStatus.REVIEWED
    )
    new = service.generate_trade_plan(
        request_data.model_copy(update={"intraday_signal": None})
    )
    assert new.plan.supersedes_plan_id == first.plan_id
    assert new.plan.action is Action.WATCH
    assert get_trade_plan(db, first.plan_id).status is TradePlanStatus.REVIEWED


def test_reduce_sells_only_exposure_above_cap(db, request_data):
    db.execute("UPDATE daily_signal SET confidence = 5")
    request = request_data.model_copy(
        update={
            "portfolio": portfolio_with(
                request_data,
                quantity=10,
                available_to_sell=10,
                position_value=1000,
            )
        }
    )
    result = TradePlanService(db).generate_trade_plan(request)
    assert result.plan.action is Action.REDUCE
    assert result.plan.position_size.quantity == Decimal(2)
    assert result.order_intent.instruction is OrderInstruction.SELL


def test_stale_portfolio_and_disabled_drafts_are_enforced(db, request_data):
    service = TradePlanService(db)
    stale = service.generate_trade_plan(
        request_data.model_copy(
            update={
                "portfolio": portfolio_with(
                    request_data,
                    observed_at=request_data.as_of - timedelta(days=2),
                )
            }
        )
    )
    assert stale.plan.action is Action.WATCH
    assert stale.order_intent is None

    db.execute(
        "UPDATE portfolio_account SET order_draft_enabled = FALSE WHERE account_id = 'SCHWAB_ROTH'"
    )
    result = service.generate_trade_plan(request_data)
    assert result.plan.action is Action.RE_ENTRY
    assert result.order_intent is None
