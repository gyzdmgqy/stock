import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from broker_gateway.csv_import import CsvImportError, CsvImportService
from shared.db import connect_database, initialize_database
from shared.db.database import ROOT
from shared.enums import Broker, ErrorType, TransactionSource, TransactionType
from shared.models import BrokerTransaction

SCHWAB = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n"
BUY = '06/05/2026,Buy,MSFT,Microsoft,2,$410.25,,"($820.50)"\n'
SELL = "06/05/2026,Sell,MSFT,Microsoft,1,$420,$0.01,$419.99\n"
VANGUARD = (
    "Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,"
    "Investment Name,Symbol,Shares,Share Price,Principal Amount,Commission Fees,Net Amount\n"
)


@pytest.fixture
def local(tmp_path):
    location = tmp_path / "test.duckdb"
    initialize_database(location)
    raw = tmp_path / "raw"
    raw.mkdir()
    with connect_database(location) as db:
        yield db, raw, CsvImportService(
            db, raw_dir=raw, archive_dir=tmp_path / "archive"
        )


def write(raw, content, name="export.csv"):
    path = raw / name
    path.write_text(content, encoding="utf-8-sig")
    return path


def schwab(service, path, **kwargs):
    return service.preview(
        path, broker=Broker.SCHWAB, account_id="SCHWAB_ROTH", **kwargs
    )


def vanguard(service, path, **kwargs):
    return service.preview(
        path, broker=Broker.VANGUARD, account_id="VANGUARD_ROTH", **kwargs
    )


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_schwab_preview_confirmation_archive_and_journal(local):
    db, raw, service = local
    path = write(raw, "Transactions for Roth IRA\n\n" + SCHWAB + BUY + SELL)
    before = path.read_bytes()
    preview = schwab(service, path)
    buy, sell = preview.transactions
    assert isinstance(buy, BrokerTransaction)
    assert buy.source is TransactionSource.CSV
    assert buy.transaction_type is TransactionType.BUY
    assert buy.quantity == Decimal("2")
    assert buy.price == Decimal("410.25")
    assert buy.gross_amount == Decimal("820.50")
    assert buy.net_amount == Decimal("-820.50")
    assert (
        buy.fee is buy.order_type is buy.settlement_date is buy.transaction_time is None
    )
    assert sell.net_amount == Decimal("419.99")
    assert count(db, "broker_transaction") == count(db, "journal_entry") == 0
    assert path.exists()
    with pytest.raises(CsvImportError) as exc:
        service.commit(preview, confirmation_token="wrong-preview")
    assert exc.value.code is ErrorType.USER_APPROVAL_REQUIRED
    assert count(db, "broker_transaction") == 0 and path.exists()

    result = service.commit(preview, confirmation_token=preview.confirmation_token)
    assert result.transactions_inserted == result.journal_entries_created == 2
    assert result.archive_path.read_bytes() == before and not path.exists()
    assert set(
        db.execute(
            "SELECT transaction_id, journal_date FROM journal_entry WHERE entry_type = 'TRADE_EXECUTION'"
        ).fetchall()
    ) == {
        (buy.transaction_id, date(2026, 6, 5)),
        (sell.transaction_id, date(2026, 6, 5)),
    }


def test_vanguard_maps_signed_sales_and_non_execution(local):
    db, raw, service = local
    path = write(
        raw,
        VANGUARD
        + "0000123,2026-06-05,2026-06-08,Sell,Sell,Fund,VOO,-0.25,500,125,0,125\n"
        + "0000123,2026-06-05,,Dividend,Dividend,Fund,QQQ,,,,,10\n",
    )
    preview = vanguard(service, path, source_account="0000123")
    sale, dividend = preview.transactions
    assert sale.broker is Broker.VANGUARD
    assert sale.quantity == Decimal("0.25")
    assert sale.settlement_date == date(2026, 6, 8)
    assert dividend.transaction_type is TransactionType.DIVIDEND
    assert dividend.quantity is dividend.price is dividend.gross_amount is None
    result = service.commit(preview, confirmation_token=preview.confirmation_token)
    assert result.transactions_inserted == 2
    assert result.journal_entries_created == count(db, "journal_entry") == 1


def test_overlapping_files_preserve_identical_fills_within_export(local):
    db, raw, service = local
    previous = schwab(service, write(raw, SCHWAB + BUY + BUY))
    service.commit(previous, confirmation_token=previous.confirmation_token)
    assert len({row.transaction_id for row in previous.transactions}) == 2
    current = schwab(service, write(raw, SCHWAB + SELL + BUY + BUY, "new.csv"))
    assert set(current.duplicate_ids) == {
        row.transaction_id for row in previous.transactions
    }
    result = service.commit(current, confirmation_token=current.confirmation_token)
    assert result.transactions_inserted == 1
    assert result.duplicates_skipped == 2
    assert count(db, "broker_transaction") == count(db, "journal_entry") == 3


def test_broker_execution_id_wins_and_conflicting_revision_is_blocked(local):
    db, raw, service = local
    header = SCHWAB.rstrip() + ",Transaction ID,Order ID\n"
    buy = BUY.rstrip() + ",fill-1,order-1\n"
    one = schwab(service, write(raw, header + buy + buy.replace("fill-1", "fill-2")))
    service.commit(one, confirmation_token=one.confirmation_token)
    repeated = schwab(service, write(raw, header + buy, "repeat.csv"))
    assert repeated.duplicate_ids == (one.transactions[0].transaction_id,)
    service.commit(repeated, confirmation_token=repeated.confirmation_token)
    assert count(db, "broker_transaction") == 2
    changed = write(raw, header + buy.replace("410.25", "400.25"), "correction.csv")
    with pytest.raises(CsvImportError, match="冲突"):
        schwab(service, changed)
    assert changed.exists()


def test_schwab_positions_and_cash_store_reported_facts_only(local):
    db, raw, service = local
    text = (
        "Roth IRA Positions\n"
        "Symbol,Description,Qty (Quantity),Price,Mkt Val (Market Value),Cost Basis,% of Acct\n"
        "MSFT,Microsoft,2,$410.25,$820.50,$800,20%\n"
        "Cash & Cash Investments,,,,$200,,\n"
        "Account Total,,,,$1020.50,,\n"
    )
    observed = datetime(2026, 6, 6, 2, tzinfo=UTC)  # 6 月 5 日，芝加哥
    first = schwab(service, write(raw, text), observed_at=observed)
    assert first.positions[0].snapshot_date == date(2026, 6, 5)
    assert first.positions[0].portfolio_weight == pytest.approx(0.2)
    assert first.cash[0].cash_balance == Decimal("200")
    assert first.cash[0].available_to_trade is None
    first_result = service.commit(first, confirmation_token=first.confirmation_token)
    assert first_result.positions_inserted == first_result.cash_inserted == 1
    assert db.execute(
        "SELECT cash_balance, available_to_trade FROM portfolio_cash_snapshot"
    ).fetchone() == (Decimal("200"), None)
    assert db.execute(
        "SELECT symbol, quantity FROM portfolio_position_snapshot"
    ).fetchone() == ("MSFT", 2)
    second = schwab(service, write(raw, text), observed_at=observed)
    assert len(second.duplicate_ids) == 2
    service.commit(second, confirmation_token=second.confirmation_token)
    assert count(db, "portfolio_cash_snapshot") == 1


def test_vanguard_combined_export_and_standalone_cash(local):
    db, raw, service = local
    path = write(
        raw,
        "Account Number,Investment Name,Symbol,Shares,Share Price,Total Value\n"
        "0000123,Fund,VOO,3,500,1500\n\n"
        + VANGUARD
        + "0000123,2026-06-05,,Buy,Buy,Fund,VOO,1,500,500,0,-500\n",
    )
    observed = datetime(2026, 6, 5, 20, tzinfo=UTC)
    preview = vanguard(service, path, observed_at=observed)
    assert preview.positions[0].symbol == "VOO" and preview.cash == ()
    assert preview.transactions[0].transaction_type is TransactionType.BUY
    service.commit(preview, confirmation_token=preview.confirmation_token)
    cash = vanguard(
        service,
        write(raw, "Currency,Cash Balance,Available to Trade\nUSD,0,10\n"),
        observed_at=observed,
    )
    assert cash.cash[0].cash_balance == Decimal("0")
    assert cash.cash[0].available_to_trade == Decimal("10")
    service.commit(cash, confirmation_token=cash.confirmation_token)
    assert (
        count(db, "portfolio_position_snapshot")
        == count(db, "portfolio_cash_snapshot")
        == 1
    )


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("a,b\n1,2\n", ErrorType.CSV_PARSE_ERROR),
        (
            SCHWAB + BUY + "06/05/2026,Buy,MSFT,,broken,410,,\n",
            ErrorType.VALIDATION_ERROR,
        ),
        (SCHWAB + '06/05/2026,Buy,MSFT,"unclosed\n', ErrorType.CSV_PARSE_ERROR),
        (SCHWAB + "06/05/2026,Buy,MSFT,,2,410,,820\n", ErrorType.VALIDATION_ERROR),
    ],
)
def test_invalid_file_causes_no_side_effects(local, content, code):
    db, raw, service = local
    path = write(raw, content)
    with pytest.raises(CsvImportError) as exc:
        schwab(service, path)
    assert exc.value.code is code
    assert path.exists() and count(db, "broker_transaction") == 0


def test_rejects_mixed_accounts_and_wrong_local_account(local):
    db, raw, service = local
    path = write(
        raw,
        VANGUARD
        + "0001,2026-06-05,,Buy,Buy,Fund,VOO,1,500,500,0,-500\n"
        + "0002,2026-06-05,,Buy,Buy,Fund,VOO,1,500,500,0,-500\n",
    )
    with pytest.raises(CsvImportError, match="多个账户"):
        vanguard(service, path, source_account="0001")
    with pytest.raises(CsvImportError, match="券商"):
        service.preview(path, broker=Broker.VANGUARD, account_id="SCHWAB_ROTH")
    assert count(db, "broker_transaction") == 0


def test_commit_rejects_changed_file_or_preview(local):
    db, raw, service = local
    path = write(raw, SCHWAB + BUY)
    preview = schwab(service, path)
    write(raw, SCHWAB + SELL)
    with pytest.raises(CsvImportError, match="重新预览"):
        service.commit(preview, confirmation_token=preview.confirmation_token)
    current = schwab(service, path)
    current.transactions[0].quantity = Decimal(900)
    with pytest.raises(CsvImportError, match="重新预览"):
        service.commit(current, confirmation_token=current.confirmation_token)
    assert path.exists() and count(db, "broker_transaction") == 0


def test_journal_failure_rolls_back_all_records(local, monkeypatch):
    from investment_journal.services.journal_service import JournalService

    db, raw, service = local
    path = write(raw, SCHWAB + BUY)
    preview = schwab(service, path)

    def fail(*args, **kwargs):
        raise ValueError("journal failure")

    with monkeypatch.context() as patch:
        patch.setattr(JournalService, "record_transaction", fail)
        with pytest.raises(CsvImportError):
            service.commit(preview, confirmation_token=preview.confirmation_token)
    assert path.exists()
    assert count(db, "broker_transaction") == count(db, "journal_entry") == 0
    service.commit(preview, confirmation_token=preview.confirmation_token)
    assert count(db, "journal_entry") == 1


def test_missing_position_is_not_cleared_by_later_export(local):
    db, raw, service = local
    header = "Symbol,Qty (Quantity),Price,Mkt Val (Market Value)\n"
    observed = datetime(2026, 6, 5, 20, tzinfo=UTC)
    first = schwab(
        service,
        write(raw, header + "AAPL,1,200,200\nMSFT,2,400,800\n"),
        observed_at=observed,
    )
    service.commit(first, confirmation_token=first.confirmation_token)
    second = schwab(
        service,
        write(raw, header + "MSFT,3,400,1200\n"),
        observed_at=observed.replace(minute=1),
    )
    service.commit(second, confirmation_token=second.confirmation_token)
    assert db.execute(
        "SELECT quantity FROM portfolio_position_snapshot WHERE symbol = 'AAPL'"
    ).fetchall() == [(1,)]


def test_archive_failure_can_be_retried_without_duplicate_writes(local, monkeypatch):
    from pathlib import Path

    db, raw, service = local
    path = write(raw, SCHWAB + BUY)
    preview = schwab(service, path)

    def unavailable(*args, **kwargs):
        raise PermissionError("archive unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", unavailable)
        with pytest.raises(CsvImportError) as exc:
            service.commit(preview, confirmation_token=preview.confirmation_token)
        assert exc.value.committed
    assert (
        path.exists()
        and count(db, "broker_transaction") == count(db, "journal_entry") == 1
    )
    retry = schwab(service, path)
    assert retry.duplicate_ids == (preview.transactions[0].transaction_id,)
    result = service.commit(retry, confirmation_token=retry.confirmation_token)
    assert result.transactions_inserted == result.journal_entries_created == 0
    assert result.archive_path.exists() and not path.exists()


def test_cli_displays_preview_and_cancel_does_not_write(local, monkeypatch, capsys):
    from contextlib import nullcontext

    from broker_gateway.csv_import import __main__ as cli

    db, raw, service = local
    path = write(raw, SCHWAB + BUY)
    monkeypatch.setattr(cli, "connect_database", lambda path: nullcontext(db))
    monkeypatch.setattr(cli, "CsvImportService", lambda db: service)
    args = ["SCHWAB", "SCHWAB_ROTH", str(path), "--db", str(raw.parent / "test.duckdb")]
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel")
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert '"transaction_type": "BUY"' in output
    assert "已取消" in output
    assert path.exists() and count(db, "broker_transaction") == 0
    monkeypatch.setattr("builtins.input", lambda prompt: "IMPORT")
    assert cli.main(args) == 0
    assert not path.exists() and count(db, "broker_transaction") == 1


def test_all_private_import_folders_are_gitignored():
    paths = [
        "imports/raw/schwab/private.csv",
        "imports/raw/vanguard/private.csv",
        "imports/normalized/private.csv",
        "imports/archive/private.csv",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == paths
    tracked = subprocess.run(
        ["git", "ls-files", "--", "imports/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout == ""
