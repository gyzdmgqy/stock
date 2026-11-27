import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from requests import Response

from broker_gateway.adapters.schwab.read_only import (
    ReadOnlyPolicy,
    SchwabReadClient,
    SchwabReadError,
    TokenMetadata,
)
from broker_gateway.adapters.schwab.sync_service import SchwabSyncService
from broker_gateway.csv_import import CsvImportError, CsvImportService
from shared.db import connect_database, initialize_database
from shared.enums import (
    Broker,
    ErrorType,
    OrderDraftStatus,
    TransactionSource,
    TransactionType,
)

NOW = datetime(2026, 6, 9, 1, 5, tzinfo=UTC)
DAY = date(2026, 6, 8)
START = NOW - timedelta(days=3)
ACCOUNT_NUMBER = "00426000"
ACCOUNT_HASH = "test-hash-not-real"
MARKER = "synthetic-secret-marker"
ROOT = "https://api.schwabapi.com/trader/v1/accounts"


def mocked_account():
    return {
        "securitiesAccount": {
            "accountNumber": ACCOUNT_NUMBER,
            "type": "CASH",
            "currentBalances": {
                "cashBalance": 1000,
                "cashAvailableForTrading": 800,
                "buyingPower": 9999,
                "liquidationValue": 10000,
            },
            "positions": [
                {
                    "instrument": {"assetType": "EQUITY", "symbol": "VRTX"},
                    "longQuantity": 5,
                    "shortQuantity": 0,
                    "averagePrice": 80,
                    "marketValue": 450,
                    "longOpenProfitLoss": 50,
                },
            ],
        }
    }


def mocked_trade(identifier=456, *, quantity=2, net=-180.13):
    return {
        "activityId": identifier,
        "accountNumber": ACCOUNT_NUMBER,
        "type": "TRADE",
        "time": "2026-06-08T19:00:00+0000",
        "tradeDate": "2026-06-08",
        "settlementDate": "2026-06-09",
        "orderId": 901,
        "netAmount": net,
        "transferItems": [
            {
                "instrument": {"assetType": "EQUITY", "symbol": "VRTX"},
                "amount": quantity,
                "price": 90,
                "cost": 180,
            },
            {
                "instrument": {"assetType": "CURRENCY", "symbol": "USD"},
                "amount": -0.13,
                "feeType": "COMMISSION",
            },
        ],
    }


class MockHTTP:
    def __init__(self, *, account=None, trades=None, orders=None):
        self.calls = []
        self.routes = {
            f"{ROOT}/accountNumbers": [
                {"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH}
            ],
            f"{ROOT}/{ACCOUNT_HASH}": (
                account if account is not None else mocked_account()
            ),
            f"{ROOT}/{ACCOUNT_HASH}/transactions": (
                trades if trades is not None else [mocked_trade()]
            ),
            f"{ROOT}/{ACCOUNT_HASH}/orders": (
                orders
                if orders is not None
                else [
                    {
                        "orderId": 901,
                        "status": "FILLED",
                        "enteredTime": "2026-06-08T18:59:00Z",
                        "quantity": 2,
                        "filledQuantity": 2,
                    },
                    {
                        "orderId": 902,
                        "status": "WORKING",
                        "quantity": 3,
                        "filledQuantity": 1,
                    },
                    {"orderId": 903, "status": "UNRECOGNIZED"},
                ]
            ),
        }

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.routes[url]
        response = Response()
        response.status_code, body = (
            result if isinstance(result, tuple) else (200, result)
        )
        response._content = json.dumps(body).encode("utf-8")
        response.headers["Location"] = "https://other.invalid"
        return response

    def post(self, *args, **kwargs):
        pytest.fail("只读客户端不得发送 POST")

    put = patch = delete = request = post


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "schwab.duckdb"
    initialize_database(path)
    with connect_database(path) as db:
        db.execute(
            "UPDATE portfolio_account SET api_sync_enabled = TRUE WHERE account_id = 'SCHWAB_ROTH'"
        )
        yield db


def credentials(**changes):
    return TokenMetadata.from_env(
        {
            "SCHWAB_ACCESS_TOKEN": MARKER,
            "SCHWAB_ACCESS_TOKEN_EXPIRES_AT": (NOW + timedelta(minutes=10)).isoformat(),
            "SCHWAB_ACCOUNT_NUMBER": ACCOUNT_NUMBER,
            **changes,
        }
    )


def syncer(db, http, *, token=None):
    client = SchwabReadClient(
        ReadOnlyPolicy(enabled=True),
        token or credentials(),
        session=http,
        clock=lambda: NOW,
    )
    return SchwabSyncService(db, client)


def test_default_disabled_and_submission_cannot_be_enabled(database):
    http = MockHTTP()
    assert ReadOnlyPolicy.from_env({}) == ReadOnlyPolicy(
        enabled=False, submission_enabled=False
    )
    for settings in (
        {},
        {"SCHWAB_API_ENABLED": "true", "ORDER_SUBMISSION_ENABLED": "true"},
    ):
        with pytest.raises(SchwabReadError) as err:
            SchwabReadClient(
                ReadOnlyPolicy.from_env(settings),
                credentials(),
                session=http,
                clock=lambda: NOW,
            )
        assert err.value.code is ErrorType.RISK_RULE_BLOCKED
    client = SchwabReadClient(
        ReadOnlyPolicy(enabled=True), credentials(), session=http, clock=lambda: NOW
    )
    assert not any(
        hasattr(client, name)
        for name in (
            "submit_order",
            "place_order",
            "replace_order",
            "cancel_order",
            "post",
            "put",
            "delete",
        )
    )
    assert http.calls == []


def test_auth_expiry_and_private_fields_are_not_logged(database):
    http = MockHTTP()
    token = credentials(SCHWAB_ACCESS_TOKEN_EXPIRES_AT=NOW.isoformat())
    assert MARKER not in repr(token) and ACCOUNT_NUMBER not in repr(token)
    with pytest.raises(SchwabReadError) as err:
        syncer(database, http, token=token).sync("SCHWAB_ROTH", as_of=NOW)
    assert err.value.code is ErrorType.AUTH_ERROR
    assert MARKER not in str(err.value) and not http.calls


@pytest.mark.parametrize("status", [302, 401, 403, 429, 502])
def test_api_failure_is_structured_and_never_follows_redirects(database, status):
    http = MockHTTP()
    http.routes[f"{ROOT}/accountNumbers"] = (status, {"private": MARKER})
    with pytest.raises(SchwabReadError) as err:
        syncer(database, http).sync("SCHWAB_ROTH", as_of=NOW)
    assert err.value.code is (
        ErrorType.AUTH_ERROR if status in (401, 403) else ErrorType.BROKER_API_ERROR
    )
    assert err.value.retryable is (status in (429, 502))
    assert http.calls[0][1]["allow_redirects"] is False
    assert MARKER not in str(err.value) and len(http.calls) == 1


@pytest.mark.parametrize(
    "violation", ["disabled", "unmapped", "wrong_response", "unsafe_hash"]
)
def test_account_binding_failures_do_not_write_or_query_wrong_accounts(
    database, violation
):
    db = database
    http = MockHTTP()
    if violation == "disabled":
        db.execute("UPDATE portfolio_account SET api_sync_enabled = FALSE")
    elif violation == "unmapped":
        http.routes[f"{ROOT}/accountNumbers"] = [
            {"accountNumber": "different", "hashValue": ACCOUNT_HASH}
        ]
    elif violation == "wrong_response":
        http.routes[f"{ROOT}/{ACCOUNT_HASH}"]["securitiesAccount"][
            "accountNumber"
        ] = "different"
    else:
        http.routes[f"{ROOT}/accountNumbers"][0]["hashValue"] = "trade/../bad?secret"
    with pytest.raises(SchwabReadError):
        syncer(db, http).sync("SCHWAB_ROTH", start=START, as_of=NOW)
    assert (
        len(http.calls)
        == {"disabled": 0, "unmapped": 1, "wrong_response": 2, "unsafe_hash": 1}[
            violation
        ]
    )
    assert db.execute(
        "SELECT count(*) FROM portfolio_position_snapshot"
    ).fetchone() == (0,)


def test_api_sync_normalizes_persists_and_is_idempotent(database):
    db = database
    http = MockHTTP(
        trades=[
            mocked_trade(),
            mocked_trade(457),
            mocked_trade(458, quantity=-2, net=179.87),
        ]
    )
    service = syncer(db, http)
    result = service.sync("SCHWAB_ROTH", start=START, orders=True, as_of=NOW)
    assert result.account.account_id == "SCHWAB_ROTH"
    assert result.account.broker_account_type == "CASH"
    assert result.account.liquidation_value == Decimal(10000)
    assert result.positions[0].snapshot_date == DAY
    assert result.positions[0].quantity == 5
    assert result.positions[0].cost_basis == 400
    assert result.positions[0].market_value == 450
    assert result.cash.available_to_trade == 800
    assert result.cash.source is TransactionSource.API
    assert len(result.transactions) == 3
    assert len({trade.deduplication_key for trade in result.transactions}) == 3
    first, _, sell = result.transactions
    assert first.transaction_type is TransactionType.BUY
    assert (first.fee, first.net_amount, first.trade_date) == (
        Decimal(".13"),
        Decimal("-180.13"),
        DAY,
    )
    assert sell.transaction_type is TransactionType.SELL and sell.quantity == 2
    assert [order.status for order in result.orders] == [
        OrderDraftStatus.FILLED,
        OrderDraftStatus.PARTIALLY_FILLED,
        OrderDraftStatus.UNKNOWN,
    ]
    assert all(
        ACCOUNT_NUMBER not in repr(item) and ACCOUNT_HASH not in repr(item)
        for item in [result]
    )
    assert [url for url, _ in http.calls] == [
        f"{ROOT}/accountNumbers",
        f"{ROOT}/{ACCOUNT_HASH}",
        f"{ROOT}/{ACCOUNT_HASH}/transactions",
        f"{ROOT}/{ACCOUNT_HASH}/orders",
    ]
    assert http.calls[1][1]["params"] == {"fields": "positions"}
    assert http.calls[2][1]["params"]["types"] == "TRADE"
    assert http.calls[3][1]["params"]["fromEnteredTime"].endswith("Z")
    assert db.execute(
        "SELECT source, count(*) FROM broker_transaction GROUP BY source"
    ).fetchall() == [("API", 3)]
    assert db.execute(
        "SELECT source, count(*) FROM portfolio_position_snapshot GROUP BY source"
    ).fetchall() == [("API", 1)]
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (3,)
    assert db.execute("SELECT count(*) FROM order_draft").fetchone() == (0,)
    assert db.execute(
        "SELECT api_sync_enabled, account_type FROM portfolio_account WHERE account_id = 'SCHWAB_ROTH'"
    ).fetchone() == (True, "ROTH_IRA")
    repeated = service.sync("SCHWAB_ROTH", start=START, orders=True, as_of=NOW)
    assert (
        repeated.positions_inserted,
        repeated.cash_inserted,
        repeated.transactions_inserted,
    ) == (0, 0, 0)
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (3,)


def test_missing_buying_cash_stays_unknown_and_no_transactions_by_default(database):
    response = mocked_account()
    response["securitiesAccount"]["currentBalances"].pop("cashAvailableForTrading")
    http = MockHTTP(account=response)
    report = syncer(database, http).sync("SCHWAB_ROTH", as_of=NOW)
    assert report.cash.cash_balance == Decimal(1000)
    assert report.cash.available_to_trade is None
    assert report.transactions == report.orders == ()
    assert len(http.calls) == 2


def csv_import(db, tmp_path, *, with_id):
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "sample.csv"
    path.write_text(
        "Date,Action,Symbol,Quantity,Price,Fees & Comm,Amount"
        + (",Transaction ID" if with_id else "")
        + "\n06/08/2026,Buy,VRTX,2,90,0.13,-180.13"
        + (",456" if with_id else "")
        + "\n",
        encoding="utf-8",
    )
    importer = CsvImportService(db, raw_dir=raw, archive_dir=tmp_path / "archive")
    return importer, path


@pytest.mark.parametrize("with_id", [False, True])
def test_api_does_not_double_count_csv(database, tmp_path, with_id):
    db = database
    importer, path = csv_import(db, tmp_path, with_id=with_id)
    preview = importer.preview(path, broker=Broker.SCHWAB, account_id="SCHWAB_ROTH")
    importer.commit(preview, confirmation_token=preview.confirmation_token)
    service = syncer(db, MockHTTP())
    if with_id:
        assert (
            service.sync("SCHWAB_ROTH", start=START, as_of=NOW).transactions_inserted
            == 0
        )
    else:
        with pytest.raises(SchwabReadError, match="不重叠"):
            service.sync("SCHWAB_ROTH", start=START, as_of=NOW)
        assert db.execute(
            "SELECT count(*) FROM portfolio_position_snapshot"
        ).fetchone() == (0,)
    assert db.execute("SELECT source FROM broker_transaction").fetchall() == [("CSV",)]
    assert db.execute("SELECT count(*) FROM journal_entry").fetchone() == (1,)


def test_csv_checks_overlap_in_reverse(database, tmp_path):
    syncer(database, MockHTTP()).sync("SCHWAB_ROTH", start=START, as_of=NOW)
    importer, path = csv_import(database, tmp_path, with_id=False)
    with pytest.raises(CsvImportError, match="不重叠"):
        importer.preview(path, broker=Broker.SCHWAB, account_id="SCHWAB_ROTH")


def test_multiple_equity_legs_are_not_guessed(database):
    bad = mocked_trade()
    bad["transferItems"].append(
        {
            "instrument": {"assetType": "EQUITY", "symbol": "MSFT"},
            "amount": 1,
            "price": 100,
        }
    )
    with pytest.raises(SchwabReadError, match="证券腿"):
        syncer(database, MockHTTP(trades=[bad])).sync(
            "SCHWAB_ROTH", start=START, as_of=NOW
        )
    assert database.execute("SELECT count(*) FROM broker_transaction").fetchone() == (
        0,
    )


def test_transport_rejects_other_hosts_and_unlisted_paths():
    http = MockHTTP()
    client = SchwabReadClient(
        ReadOnlyPolicy(enabled=True), credentials(), session=http, clock=lambda: NOW
    )
    for url in (
        "https://other.invalid/trader/v1/accounts/accountNumbers",
        f"{ROOT}/{ACCOUNT_HASH}/previewOrder",
    ):
        with pytest.raises(SchwabReadError) as err:
            client._get(url)
        assert err.value.code is ErrorType.RISK_RULE_BLOCKED
    assert not http.calls


def test_execution_journal_failure_rolls_back_sync(database, monkeypatch):
    from investment_journal.services.journal_service import JournalService

    def fail_journal(*args, **kwargs):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(JournalService, "record_transaction", fail_journal)
    with pytest.raises(RuntimeError, match="journal unavailable"):
        syncer(database, MockHTTP()).sync("SCHWAB_ROTH", start=START, as_of=NOW)
    for table in (
        "broker_transaction",
        "portfolio_position_snapshot",
        "portfolio_cash_snapshot",
        "journal_entry",
    ):
        assert database.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_cli_requires_explicit_local_acceptance_and_off_by_default(monkeypatch, capsys):
    from scripts import sync_schwab_read_only as cli

    monkeypatch.setattr(cli, "_runtime_env", lambda: {})
    assert cli.main([]) == 1
    assert "验收" in capsys.readouterr().err
    assert cli.main(["--confirm-local-acceptance"]) == 1
    assert "RISK_RULE_BLOCKED" in capsys.readouterr().err


def test_currency_fee_known_by_cost_does_not_become_zero(database):
    row = mocked_trade()
    row["transferItems"][1].update(amount=0, cost=-0.13)
    result = syncer(database, MockHTTP(trades=[row])).sync(
        "SCHWAB_ROTH", start=START, as_of=NOW
    )
    assert result.transactions[0].fee == Decimal("0.13")


def test_confirmed_csv_id_does_not_block_separate_identical_api_fill(
    database, tmp_path
):
    importer, path = csv_import(database, tmp_path, with_id=True)
    preview = importer.preview(path, broker=Broker.SCHWAB, account_id="SCHWAB_ROTH")
    importer.commit(preview, confirmation_token=preview.confirmation_token)
    result = syncer(
        database, MockHTTP(trades=[mocked_trade(457), mocked_trade(456)])
    ).sync(
        "SCHWAB_ROTH",
        start=START,
        as_of=NOW,
    )
    assert result.transactions_inserted == 1
    assert database.execute(
        "SELECT source, broker_transaction_id FROM broker_transaction ORDER BY source"
    ).fetchall() == [
        ("API", "457"),
        ("CSV", "456"),
    ]
