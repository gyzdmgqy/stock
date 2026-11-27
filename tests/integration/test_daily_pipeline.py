import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import exchange_calendars
import pytest

from broker_gateway.csv_import import CsvImportService
from market_data.repositories.daily_price_repository import DailyPriceRepository
from scripts.run_daily_pipeline import run_daily_pipeline
from shared.db import connect_database, initialize_database
from shared.db.database import DEFAULT_CONFIG_DIR, ROOT
from shared.enums import Action, Broker, OrderDraftStatus
from shared.models import DailyPrice

DAY = date(2026, 6, 8)
NOW = datetime(2026, 6, 8, 20, 15, tzinfo=UTC)
OBSERVED = NOW - timedelta(minutes=15)


class SamplePrices:
    def __init__(self, day=DAY):
        self.day = day
        self.calendar = exchange_calendars.get_calendar("XNYS")
        self.calls = []

    def fetch_daily_prices(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        last = self.calendar.previous_session(self.day).date()
        bars = []
        for session in self.calendar.sessions_in_range(start, end):
            day = session.date()
            close = 90 if symbol == "VRTX" and day in (last, self.day) else 100
            bars.append(
                DailyPrice(
                    symbol=symbol,
                    trade_date=day,
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=100,
                    source="sample",
                )
            )
        return bars


class ReentryPrices(SamplePrices):
    def fetch_daily_prices(self, symbol, start, end):
        bars = super().fetch_daily_prices(symbol, start, end)
        if symbol != "MSFT":
            return bars
        updated = []
        for bar in bars:
            fields = bar.model_dump()
            if bar.trade_date == self.day:
                fields.update(open=100, high=103, low=97, close=102.9, volume=150)
            elif bar.trade_date == self.calendar.previous_session(self.day).date():
                fields.update(close=99.5)
            updated.append(DailyPrice.model_validate(fields))
        return updated


@pytest.fixture
def local(tmp_path):
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    (config / "symbols.yaml").write_text(
        "core_index: [SPY]\nactive_watchlist: [VRTX, MSFT]\n", encoding="utf-8"
    )
    path = tmp_path / "pipeline.duckdb"
    initialize_database(path, config_dir=config)
    with connect_database(path) as db:
        yield db, config, tmp_path


def run(local, *, provider=None, as_of=NOW, supplemental=None):
    db, config, root = local
    return run_daily_pipeline(
        db,
        config_dir=config,
        output_dir=root / "outputs",
        provider=provider,
        as_of=as_of,
        planning_inputs_path=supplemental,
    )


def counts(db):
    names = (
        "daily_price",
        "daily_indicator",
        "daily_signal",
        "signal_detail",
        "trade_plan",
        "order_draft",
        "approval_record",
        "daily_cio_brief",
        "journal_entry",
    )
    return dict(
        (name, db.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
        for name in names
    )


def import_snapshots(local, *, observed=OBSERVED):
    db, _, root = local
    raw = root / "raw"
    raw.mkdir()
    importer = CsvImportService(db, raw_dir=raw, archive_dir=root / "archive")
    for broker, account, text in (
        (
            Broker.SCHWAB,
            "SCHWAB_ROTH",
            "Symbol,Qty (Quantity),Price,Mkt Val (Market Value)\nVRTX,5,90,450\n"
            "\nCurrency,Cash Balance,Available to Trade\nUSD,1000,800\n",
        ),
        (
            Broker.VANGUARD,
            "VANGUARD_ROTH",
            "Account Number,Investment Name,Symbol,Shares,Share Price,Total Value\n"
            "123,Fund,VRTX,2,90,180\n",
        ),
    ):
        path = raw / f"{broker.value}.csv"
        path.write_text(text, encoding="utf-8")
        preview = importer.preview(
            path, broker=broker, account_id=account, observed_at=observed
        )
        importer.commit(preview, confirmation_token=preview.confirmation_token)
    db.executemany(
        "INSERT INTO portfolio_risk_snapshot "
        "(snapshot_id, account_id, snapshot_date, total_market_value, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("s", "SCHWAB_ROTH", DAY, 10000, OBSERVED),
            ("v", "VANGUARD_ROTH", DAY, 50000, OBSERVED),
        ],
    )


def confirm_sell(local, *, observed=OBSERVED):
    path = local[2] / "planning.yaml"
    path.write_text(
        f"""reviews:
  - account_id: SCHWAB_ROTH
    symbol: VRTX
    observed_at: "{observed.isoformat()}"
    has_open_order: false
    available_to_sell: 5
    exit_limit_price: 89
""",
        encoding="utf-8",
    )
    return path


def test_daily_pipeline_uses_imports_and_is_idempotent(local):
    db, _, root = local
    import_snapshots(local)
    evidence = confirm_sell(local)
    provider = SamplePrices()
    first = run(local, provider=provider, supplemental=evidence)
    assert [call[0] for call in provider.calls] == ["SPY", "VRTX", "MSFT"]
    assert {signal.symbol for signal in first.signals} == {"SPY", "VRTX", "MSFT"}
    plans = {(plan.account_id, plan.symbol): plan for plan in first.plans}
    assert plans["SCHWAB_ROTH", "VRTX"].action is Action.EXIT
    assert plans["SCHWAB_ROTH", "MSFT"].action is Action.WATCH
    assert plans["VANGUARD_ROTH", "VRTX"].action is Action.EXIT_ONLY
    assert len(first.drafts) == 1 and first.drafts[0].quantity == 5
    assert first.drafts[0].status is OrderDraftStatus.PENDING_REVIEW
    assert first.brief.market_summary.market_regime is not None
    assert first.brief.portfolio_summary.total_value == 60000
    assert first.brief.order_draft_summary[0].draft_id == first.drafts[0].draft_id
    expected_files = [
        "briefs/2026-06-08_Daily_CIO_Brief.md",
        "briefs/2026-06-08_Daily_CIO_Brief.json",
        "trade_plans/2026-06-08_trade_plans.json",
        "order_drafts/2026-06-08_order_drafts.json",
        "journal/2026-06-08_journal.json",
    ]
    assert all((root / "outputs" / filename).is_file() for filename in expected_files)
    journal = json.loads(
        (root / "outputs" / expected_files[-1]).read_text(encoding="utf-8")
    )
    assert {entry["entry_type"] for entry in journal} == {
        "SIGNAL_REVIEW",
        "TRADE_PLAN_REVIEW",
        "ORDER_REVIEW",
        "DAILY",
    }
    before = counts(db)
    assert before["approval_record"] == 0 and before["daily_cio_brief"] == 1
    assert (
        before["journal_entry"]
        == len(first.signals) + len(first.plans) + len(first.drafts) + 1
    )
    db.execute(
        "UPDATE journal_entry SET user_note = '人工备注' WHERE entry_type = 'DAILY'"
    )
    again = run(
        local,
        provider=provider,
        as_of=NOW + timedelta(minutes=5),
        supplemental=evidence,
    )
    assert len(provider.calls) == 3 and before == counts(db)
    assert [item.plan_id for item in again.plans] == [
        item.plan_id for item in first.plans
    ]
    assert again.drafts == first.drafts and again.brief.brief_id == first.brief.brief_id
    assert again.brief.created_at == first.brief.created_at
    assert db.execute(
        "SELECT user_note FROM journal_entry WHERE entry_type = 'DAILY'"
    ).fetchone() == ("人工备注",)


@pytest.mark.parametrize(
    "mode", ["missing_confirmation", "stale_confirmation", "stale_position"]
)
def test_uncertain_portfolio_inputs_are_visible_and_never_create_drafts(local, mode):
    stale = NOW - timedelta(hours=25)
    import_snapshots(local, observed=stale if mode == "stale_position" else OBSERVED)
    manual = None
    if mode != "missing_confirmation":
        manual = confirm_sell(
            local, observed=stale if mode == "stale_confirmation" else OBSERVED
        )
    result = run(local, provider=SamplePrices(), supplemental=manual)
    plan = next(
        p for p in result.plans if (p.account_id, p.symbol) == ("SCHWAB_ROTH", "VRTX")
    )
    assert plan.action is Action.WATCH and not result.drafts
    assert any("SCHWAB_ROTH" in item for item in result.brief.risk_summary.key_risks)


def test_offline_missing_session_does_not_reuse_old_signal(local):
    db, _, _ = local
    provider = SamplePrices()
    start = DAY - timedelta(days=350)
    DailyPriceRepository(db).upsert_daily_prices(
        provider.fetch_daily_prices("SPY", start, date(2026, 6, 5))
    )
    result = run(local)
    assert not result.signals and not result.plans and not result.drafts
    assert result.brief.market_summary.market_regime is None
    assert any(
        "SPY" in item and "日线" in item for item in result.brief.risk_summary.key_risks
    )
    assert counts(db)["journal_entry"] == 1


def test_only_missing_sessions_are_downloaded(local):
    db, _, _ = local
    provider = SamplePrices()
    missing = date(2026, 6, 5)
    repo = DailyPriceRepository(db)
    bars = provider.fetch_daily_prices("SPY", DAY - timedelta(days=350), DAY)
    repo.upsert_daily_prices(bar for bar in bars if bar.trade_date != missing)
    provider.calls.clear()
    run(local, provider=provider)
    assert [call for call in provider.calls if call[0] == "SPY"] == [
        ("SPY", missing, missing)
    ]
    assert repo.get_daily_prices("SPY", DAY, DAY)[0].created_at is not None


def test_exchange_calendar_skips_holiday_and_incomplete_session(local):
    provider = SamplePrices(day=date(2026, 11, 27))
    for instant in (
        datetime(2026, 11, 26, 21, tzinfo=UTC),
        datetime(2026, 11, 27, 17, 59, tzinfo=UTC),
    ):
        result = run(local, provider=provider, as_of=instant)
        assert result.skipped_reason and result.brief is None
    assert not provider.calls and counts(local[0])["daily_cio_brief"] == 0
    late = datetime(2026, 11, 27, 18, 5, tzinfo=UTC)
    import_snapshots(local, observed=late - timedelta(minutes=5))
    evidence = confirm_sell(local, observed=late - timedelta(minutes=5))
    result = run(local, provider=provider, as_of=late, supplemental=evidence)
    assert result.brief.brief_date == date(2026, 11, 27)
    assert len(result.drafts) == 1
    assert all(end <= result.brief.brief_date for _, _, end in provider.calls)


def test_broker_draft_toggle_does_not_remove_plans(local):
    import_snapshots(local)
    _, config, _ = local
    path = config / "broker.yaml"
    body = path.read_text(encoding="utf-8")
    path.write_text(
        body.replace("order_draft_enabled: true", "order_draft_enabled: false"),
        encoding="utf-8",
    )
    result = run(local, provider=SamplePrices(), supplemental=confirm_sell(local))
    assert any(plan.action is Action.EXIT for plan in result.plans)
    assert not result.drafts and counts(local[0])["order_draft"] == 0


def test_adjacent_run_does_not_reversion_unchanged_previous_analysis(local):
    db, _, _ = local
    prices = SamplePrices()
    friday = run(local, provider=prices, as_of=datetime(2026, 6, 5, 20, 15, tzinfo=UTC))
    run(local, provider=prices)
    assert db.execute(
        "SELECT signal_id FROM daily_signal WHERE trade_date = ? AND symbol = 'SPY'",
        [friday.day],
    ).fetchall() == [(next(s.signal_id for s in friday.signals if s.symbol == "SPY"),)]


def test_incomplete_replay_preserves_history_but_excludes_its_old_draft(local):
    db, _, _ = local
    import_snapshots(local)
    evidence = confirm_sell(local)
    original = run(local, provider=SamplePrices(), supplemental=evidence)
    db.execute(
        "DELETE FROM daily_price WHERE symbol IN ('VRTX', 'SPY') AND trade_date = ?",
        [DAY],
    )
    replay = run(local, supplemental=evidence)
    assert original.drafts and not replay.drafts
    assert counts(db)["order_draft"] == 1
    assert replay.brief.market_summary.market_regime is None
    assert not replay.brief.order_draft_summary


def test_reentry_only_when_explicit_hourly_and_other_evidence_exists(local):
    _, _, root = local
    import_snapshots(local)
    proof = root / "planning.yaml"
    setup = f"""reviews:
  - account_id: SCHWAB_ROTH
    symbol: MSFT
    observed_at: "{OBSERVED.isoformat()}"
    has_open_order: false
    confirmed_flat: true
    reentry_candidate: true
    combined_symbol_value: 0
    combined_sector_value: 0
    earnings_checked_through: 2026-06-15
    entry_prices: {{limit_price: 100, stop_price: 95, target_price: 115}}
"""
    proof.write_text(setup, encoding="utf-8")
    first = run(local, provider=ReentryPrices(), supplemental=proof)
    assert not first.drafts
    assert any(
        plan.action is Action.WATCH for plan in first.plans if plan.symbol == "MSFT"
    )
    proof.write_text(
        setup + """    intraday_signal:
      signal_id: MSFT-HOUR-1
      symbol: MSFT
      trade_date: 2026-06-08
      bar_start: "2026-06-08T18:30:00Z"
      hourly_trend: HIGHER_LOW_CONFIRMED
      vwap_status: ABOVE_VWAP
""",
        encoding="utf-8",
    )
    second = run(local, supplemental=proof)
    assert any(plan.action is Action.RE_ENTRY for plan in second.plans)
    assert len(second.drafts) == 1
    assert second.drafts[0].symbol == "MSFT" and second.drafts[0].instruction == "BUY"


def test_script_cli_is_runnable_from_outside_repository(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_daily_pipeline.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert b"--offline" in result.stdout
