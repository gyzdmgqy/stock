import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.enums import AccountRole, OrderDraftStatus, TradePlanStatus
from shared.models import (
    ApprovalDecision,
    BrokerTransaction,
    DailyCioBrief,
    DailyPrice,
    DailySignal,
    IntradayPrice,
    IntradaySignal,
    JournalEntry,
    OrderDraft,
    PortfolioSnapshot,
    TradePlan,
)

TRADE_DATE = "2026-06-05"
BAR_START = "2026-06-05T14:30:00-05:00"
MODEL_CASES = [
    (DailyPrice, {"symbol": "VOO", "trade_date": TRADE_DATE}, "trade_date"),
    (
        IntradayPrice,
        {"symbol": "VOO", "trade_date": TRADE_DATE, "bar_start": BAR_START},
        "bar_start",
    ),
    (
        DailySignal,
        {"signal_id": "SIG-1", "symbol": "VOO", "trade_date": TRADE_DATE},
        "signal_id",
    ),
    (
        IntradaySignal,
        {
            "signal_id": "ISIG-1",
            "symbol": "VOO",
            "trade_date": TRADE_DATE,
            "bar_start": BAR_START,
        },
        "trade_date",
    ),
    (
        PortfolioSnapshot,
        {
            "snapshot_id": "POS-1",
            "snapshot_date": TRADE_DATE,
            "symbol": "VOO",
            "account_id": "VANGUARD_ROTH",
            "broker": "VANGUARD",
            "account_role": "CORE_PASSIVE",
        },
        "account_id",
    ),
    (
        BrokerTransaction,
        {
            "transaction_id": "TXN-1",
            "account_id": "SCHWAB_ROTH",
            "broker": "SCHWAB",
            "transaction_type": "TRANSFER",
            "source": "CSV",
            "net_amount": "-200.50",
        },
        "source",
    ),
    (
        TradePlan,
        {
            "plan_id": "TP-1",
            "plan_date": TRADE_DATE,
            "symbol": "VOO",
            "account_id": "VANGUARD_ROTH",
            "account_role": "CORE_PASSIVE",
            "action": "WATCH",
        },
        "action",
    ),
    (
        OrderDraft,
        {
            "draft_id": "OD-1",
            "plan_id": "TP-1",
            "account_id": "SCHWAB_ROTH",
            "broker": "SCHWAB",
            "symbol": "VOO",
            "instruction": "BUY",
            "order_type": "LIMIT",
            "quantity": "1.25",
            "limit_price": "512.10",
        },
        "quantity",
    ),
    (
        ApprovalDecision,
        {
            "approval_id": "APR-1",
            "draft_id": "OD-1",
            "plan_id": "TP-1",
            "decision": "DEFERRED",
            "decided_at": BAR_START,
        },
        "decided_at",
    ),
    (
        JournalEntry,
        {
            "journal_id": "JRN-1",
            "journal_date": TRADE_DATE,
            "entry_type": "MANUAL_NOTE",
        },
        "entry_type",
    ),
    (DailyCioBrief, {"brief_id": "BRIEF-1", "brief_date": TRADE_DATE}, "brief_date"),
]


@pytest.mark.parametrize(("model", "payload", "required"), MODEL_CASES)
def test_required_fields_and_json_round_trip(model, payload, required):
    item = model.model_validate(payload)
    assert model.model_validate_json(item.model_dump_json()) == item

    with pytest.raises(ValidationError) as error:
        model.model_validate(
            {key: value for key, value in payload.items() if key != required}
        )
    assert error.value.errors()[0]["loc"] == (required,)


def test_portfolio_roles_are_typed_and_neutral():
    payload = MODEL_CASES[4][1]
    passive = PortfolioSnapshot.model_validate(payload)
    active = PortfolioSnapshot.model_validate(
        {
            **payload,
            "account_id": "SCHWAB_ROTH",
            "broker": "SCHWAB",
            "account_role": "ACTIVE_TRADING",
        }
    )
    assert passive.account_role is AccountRole.CORE_PASSIVE
    assert active.account_role is AccountRole.ACTIVE_TRADING


@pytest.mark.parametrize(
    ("case", "updates"),
    [
        (0, {"volume": -1}),
        (0, {"symbol": " "}),
        (1, {"bar_start": "2026-06-05T14:30:00"}),
        (2, {"confidence": 100.1}),
        (2, {"action_hint": "WAIT_FOR_LIMIT_ENTRY"}),
        (3, {"action_hint": "WATCH"}),
        (3, {"interval": "daily"}),
        (4, {"portfolio_weight": 1.01}),
        (5, {"source": "FTP"}),
        (6, {"action": "ENTER"}),
        (6, {"action": "RE_ENTRY"}),
        (6, {"action": "RE_ENTRY", "invalid_condition": [" "]}),
        (6, {"action": "EXIT_ONLY"}),
        (6, {"stop_order": {"type": "STOP", "stop_price": "425.00"}}),
        (7, {"quantity": "0"}),
        (7, {"order_type": "STRUCTURE_CONFIRMATION"}),
        (7, {"limit_price": None}),
        (7, {"limit_price": "-1.00"}),
        (7, {"stop_price": "400.00"}),
        (8, {"decision": "APPROVED"}),
        (9, {"entry_type": "NOTE"}),
        (9, {"discipline_score": -1}),
        (
            10,
            {
                "trade_plan_summary": [
                    {"plan_id": "TP-1", "symbol": "VOO", "action": "ENTER"}
                ]
            },
        ),
    ],
)
def test_rejects_invalid_values(case, updates):
    model, payload, _ = MODEL_CASES[case]
    with pytest.raises(ValidationError):
        model.model_validate({**payload, **updates})


def test_defaults_and_nested_plan_fields():
    plan = TradePlan.model_validate(
        {
            **MODEL_CASES[6][1],
            "action": "ADD",
            "invalid_condition": ["close_below_ma200"],
            "stop_order": {
                "type": "STRUCTURE_CONFIRMATION",
                "condition": "close_below_ma200",
            },
            "entry_order": {"type": "LIMIT", "price": "512.10"},
            "position_size": {
                "percent_of_portfolio": 1.5,
                "sizing_base_value": "450000",
            },
        }
    )
    order = OrderDraft.model_validate(MODEL_CASES[7][1])
    assert plan.status is TradePlanStatus.DRAFT
    assert order.status is OrderDraftStatus.PENDING_REVIEW
    assert order.quantity == Decimal("1.25")
    assert plan.entry_order.price == Decimal("512.10")
    assert plan.position_size.sizing_basis == "ACCOUNT"
    assert (
        IntradayPrice.model_validate(MODEL_CASES[1][1])
        .bar_start.utcoffset()
        .total_seconds()
        == 0
    )


def test_documented_messages_validate():
    protocol = (
        Path(__file__).resolve().parents[3] / "docs/05_Agent_Communication_Protocol.md"
    )
    document = protocol.read_text(encoding="utf-8")
    for heading, model in (
        ("# 7. Daily Signal Schema", DailySignal),
        ("# 8. Intraday Signal Schema", IntradaySignal),
        ("# 10. Portfolio Snapshot Schema", PortfolioSnapshot),
        ("# 11. Broker Transaction Schema", BrokerTransaction),
        ("# 12. Trade Plan Schema", TradePlan),
        ("# 14. Vanguard Exit Plan Schema", TradePlan),
        ("# 15. Order Draft Schema", OrderDraft),
        ("# 16. Approval Decision Schema", ApprovalDecision),
        ("# 17. Daily CIO Brief Schema", DailyCioBrief),
        ("# 18. Journal Entry Schema", JournalEntry),
    ):
        payload = (
            document.split(heading, 1)[1].split("```json\n", 1)[1].split("```", 1)[0]
        )
        item = model.model_validate(json.loads(payload))
        assert model.model_validate_json(item.model_dump_json()) == item
