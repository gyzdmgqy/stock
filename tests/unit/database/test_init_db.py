from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from shutil import copytree
from subprocess import run
from sys import executable

import duckdb
import pytest
from pydantic import ValidationError

from shared.db import (
    MigrationError,
    connect_database,
    get_journal_entry,
    get_trade_plan,
    initialize_database,
    insert_journal_entry,
    insert_trade_plan,
)
from shared.models import JournalEntry, TradePlan

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "shared/db/migrations"

TABLES = {
    "symbol",
    "watchlist",
    "watchlist_symbol",
    "daily_price",
    "intraday_price",
    "corporate_event",
    "macro_event",
    "news_item",
    "daily_indicator",
    "daily_signal",
    "signal_detail",
    "portfolio_account",
    "portfolio_position_snapshot",
    "portfolio_risk_snapshot",
    "portfolio_cash_snapshot",
    "broker_transaction",
    "trade_plan",
    "trade_plan_signal_link",
    "order_draft",
    "approval_record",
    "daily_cio_brief",
    "journal_entry",
    "trade_outcome",
    "performance_review",
    "backtest_run",
    "backtest_trade",
    "backtest_metric",
}
SYMBOLS = set("SPY QQQ VOO MSFT AAPL NVDA GOOGL AMZN META VRTX COST AVGO LLY".split())
INDEXES = {
    "idx_daily_price_symbol_date",
    "idx_daily_indicator_symbol_date",
    "idx_daily_signal_symbol_date",
    "idx_position_snapshot_date_symbol",
    "idx_trade_plan_date_symbol",
    "idx_order_draft_status_date",
    "idx_daily_cio_brief_date",
}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "test.duckdb"


@pytest.fixture
def plan():
    return TradePlan.model_validate(
        {
            "plan_id": "TP-1",
            "symbol": "VRTX",
            "plan_date": "2026-06-05",
            "account_id": "SCHWAB_ROTH",
            "account_role": "ACTIVE_TRADING",
            "action": "ADD",
            "strategy_type": "TREND_FOLLOWING",
            "status": "REVIEWED",
            "execution_timeframe": "1h",
            "rule_version": "test-v1",
            "input_references": [{"table": "daily_signal", "row_id": "SIG-1"}],
            "entry_condition": ["daily_close_above_ma200"],
            "entry_order": {"type": "LIMIT", "price": "450.123456"},
            "stop_order": {
                "type": "STOP_LIMIT",
                "stop_price": "425.120001",
                "limit_price": "420.120001",
                "condition": "break_support",
                "reason": "结构风险",
            },
            "target_price_1": "99999999999999.123456",
            "target_price_2": "520.000001",
            "position_size": {
                "percent_of_portfolio": 1.5,
                "estimated_value": "6750.123456",
                "quantity": "14.12345678",
                "sizing_basis": "ACCOUNT",
                "sizing_base_value": "450000.100001",
            },
            "invalid_condition": ["close_below_ma200", "source_data_stale"],
            "exit_trigger": ["risk_trigger"],
            "replacement": {"VOO": 0.6, "QQQ": 0.4},
            "future_reentry_account": "SCHWAB_ROTH",
            "confidence": 80,
            "created_at": "2026-06-05T12:00:00-05:00",
            "updated_at": "2026-06-05T13:00:00-05:00",
        }
    )


def test_init_creates_schema_indexes_and_seeds(db_path):
    assert initialize_database(db_path) == 1
    assert db_path.is_file()
    with connect_database(db_path, read_only=True) as db:
        assert {row[0] for row in db.execute("SHOW TABLES").fetchall()} == TABLES | {
            "_schema_migrations"
        }
        assert {
            row[0]
            for row in db.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
        } == INDEXES
        assert {
            row[0] for row in db.execute("SELECT symbol FROM symbol").fetchall()
        } == SYMBOLS
        assert dict(
            db.execute(
                "SELECT account_id, account_role FROM portfolio_account"
            ).fetchall()
        ) == {
            "VANGUARD_ROTH": "CORE_PASSIVE",
            "SCHWAB_ROTH": "ACTIVE_TRADING",
        }
        assert db.execute(
            "SELECT individual_stock_policy, api_sync_enabled, default_replacement "
            "FROM portfolio_account WHERE account_id = 'VANGUARD_ROTH'"
        ).fetchone() == ("EXIT_ONLY", False, None)
        assert {
            row[0]
            for row in db.execute("SELECT watchlist_id FROM watchlist").fetchall()
        } == {
            "core_index",
            "active_watchlist",
            "long_term_compounders",
            "medical_leaders",
            "ai_leaders",
        }
        assert db.execute(
            "SELECT symbol FROM watchlist_symbol WHERE watchlist_id = 'core_index' ORDER BY priority"
        ).fetchall() == [("VOO",), ("QQQ",), ("SPY",)]
        assert db.execute("SELECT current_setting('TimeZone')").fetchone() == ("UTC",)


def test_reinitialization_preserves_existing_records_and_restores_missing_seeds(
    db_path, plan
):
    initialize_database(db_path)
    with connect_database(db_path) as db:
        db.execute(
            "UPDATE portfolio_account SET account_name = '自定义' WHERE account_id = 'SCHWAB_ROTH'"
        )
        db.execute("DELETE FROM symbol WHERE symbol = 'SPY'")
        db.execute(
            "UPDATE watchlist_symbol SET note = '保留备注' WHERE watchlist_id = 'core_index' AND symbol = 'VOO'"
        )
        insert_trade_plan(db, plan)
        db.execute(
            "INSERT INTO approval_record (approval_id, plan_id, decision) VALUES ('APR-1', ?, 'DEFERRED')",
            [plan.plan_id],
        )
        insert_journal_entry(
            db,
            JournalEntry(
                journal_id="J-1",
                journal_date="2026-06-05",
                entry_type="MANUAL_NOTE",
                user_note="保留日志",
            ),
        )

    assert initialize_database(db_path) == 1
    with connect_database(db_path, read_only=True) as db:
        assert db.execute("SELECT count(*) FROM _schema_migrations").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM symbol").fetchone() == (len(SYMBOLS),)
        assert db.execute(
            "SELECT account_name FROM portfolio_account WHERE account_id = 'SCHWAB_ROTH'"
        ).fetchone() == ("自定义",)
        assert db.execute(
            "SELECT note FROM watchlist_symbol WHERE watchlist_id = 'core_index' AND symbol = 'VOO'"
        ).fetchone() == ("保留备注",)
        assert get_trade_plan(db, plan.plan_id) == plan
        assert db.execute(
            "SELECT decision FROM approval_record WHERE approval_id = 'APR-1'"
        ).fetchone() == ("DEFERRED",)
        assert get_journal_entry(db, "J-1").user_note == "保留日志"


def test_trade_plan_and_rich_journal_round_trip_after_reopen(db_path, plan):
    initialize_database(db_path)
    journal = JournalEntry.model_validate(
        {
            "journal_id": "J-RICH",
            "journal_date": plan.plan_date,
            "entry_type": "TRADE_PLAN_REVIEW",
            "symbol": plan.symbol,
            "account_id": plan.account_id,
            "plan_id": plan.plan_id,
            "draft_id": "OD-1",
            "transaction_id": "TX-1",
            "action": plan.action,
            "thesis": "观察均线",
            "decision_reason": "等待确认",
            "user_note": "复盘",
            "system_note": "生成于本地",
            "market_regime": "RANGE",
            "strategy_type": plan.strategy_type,
            "confidence": 80,
            "emotion_tag": "CALM",
            "discipline_score": 92,
            "outcome_5d": -0.125,
            "outcome_20d": None,
            "outcome_60d": 0.2,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }
    )
    with connect_database(db_path) as db:
        insert_trade_plan(db, plan)
        db.execute(
            "INSERT INTO order_draft (draft_id, plan_id, broker, account_id, symbol) VALUES ('OD-1', ?, 'SCHWAB', ?, ?)",
            [plan.plan_id, plan.account_id, plan.symbol],
        )
        db.execute(
            "INSERT INTO broker_transaction (transaction_id, broker, account_id, symbol, transaction_type, plan_id, draft_id, source, deduplication_key) "
            "VALUES ('TX-1', 'SCHWAB', ?, ?, 'BUY', ?, 'OD-1', 'CSV', 'sample-row')",
            [plan.account_id, plan.symbol, plan.plan_id],
        )
        insert_journal_entry(db, journal)

    with connect_database(db_path, read_only=True) as db:
        assert get_trade_plan(db, plan.plan_id) == plan
        assert get_journal_entry(db, journal.journal_id) == journal
        assert get_trade_plan(db, "missing") is None
        assert get_journal_entry(db, "missing") is None
        assert db.execute(
            "SELECT entry_price, quantity, json_extract_string(entry_condition, '$[0]') "
            "FROM trade_plan WHERE plan_id = ?",
            [plan.plan_id],
        ).fetchone() == (
            Decimal("450.123456"),
            Decimal("14.12345678"),
            "daily_close_above_ma200",
        )


def test_empty_nested_object_is_distinct_from_missing_and_created_at_defaults(
    db_path, plan
):
    initialize_database(db_path)
    data = {
        **plan.model_dump(),
        "action": "WATCH",
        "entry_order": None,
        "stop_order": None,
        "created_at": None,
    }
    with connect_database(db_path) as db:
        for plan_id, size in (("absent", None), ("empty", {})):
            item = TradePlan.model_validate(
                {**data, "plan_id": plan_id, "position_size": size}
            )
            insert_trade_plan(db, item)
            saved = get_trade_plan(db, plan_id)
            assert saved.position_size == item.position_size
            assert saved.entry_order is None
            assert saved.stop_order is None
            assert isinstance(saved.created_at, datetime)
            assert saved.created_at.tzinfo is UTC


def test_persistence_checks_links_and_revalidates_models(db_path, plan):
    initialize_database(db_path)
    with connect_database(db_path) as db:
        with pytest.raises(ValueError, match="account_id"):
            insert_trade_plan(db, plan.model_copy(update={"account_id": "unknown"}))
        insert_trade_plan(db, plan)
        with pytest.raises(duckdb.ConstraintException):
            insert_trade_plan(db, plan.model_copy(update={"reason": "不能覆盖"}))
        with pytest.raises(ValueError, match="account_id"):
            insert_journal_entry(
                db,
                JournalEntry(
                    journal_id="J-1",
                    journal_date=plan.plan_date,
                    entry_type="TRADE_PLAN_REVIEW",
                    account_id="VANGUARD_ROTH",
                    plan_id=plan.plan_id,
                ),
            )
        with pytest.raises(ValueError, match="draft_id"):
            insert_journal_entry(
                db,
                JournalEntry(
                    journal_id="J-2",
                    journal_date=plan.plan_date,
                    entry_type="ORDER_REVIEW",
                    draft_id="missing",
                ),
            )
        plan.invalid_condition.clear()
        with pytest.raises(ValidationError):
            insert_trade_plan(db, plan.model_copy(update={"plan_id": "TP-2"}))
        db.execute("UPDATE trade_plan SET status = 'INVALID' WHERE plan_id = 'TP-1'")
        with pytest.raises(ValidationError):
            get_trade_plan(db, "TP-1")


def test_versioned_upgrade_applies_once_and_rejects_changed_history(db_path, tmp_path):
    initialize_database(db_path)
    folder = tmp_path / "migrations"
    copytree(MIGRATIONS, folder)
    migration = folder / "0002_sample_upgrade.sql"
    migration.write_text(
        "ALTER TABLE symbol ADD COLUMN test_metadata TEXT;", encoding="utf-8"
    )

    assert initialize_database(db_path, migrations_dir=folder) == 2
    assert initialize_database(db_path, migrations_dir=folder) == 2
    with connect_database(db_path, read_only=True) as db:
        assert db.execute(
            "SELECT version FROM _schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
        assert db.execute("SELECT count(test_metadata) FROM symbol").fetchone() == (0,)
    with pytest.raises(MigrationError, match="版本"):
        initialize_database(db_path)
    migration.write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="修改"):
        initialize_database(db_path, migrations_dir=folder)


def test_failing_migration_rolls_back_ddl_and_version(db_path, tmp_path):
    initialize_database(db_path)
    folder = tmp_path / "migrations"
    copytree(MIGRATIONS, folder)
    (folder / "0002_invalid_upgrade.sql").write_text(
        "CREATE TABLE rollback_probe (id INT); INSERT INTO missing_table VALUES (1);",
        encoding="utf-8",
    )
    with pytest.raises(MigrationError, match="0002"):
        initialize_database(db_path, migrations_dir=folder)
    with connect_database(db_path, read_only=True) as db:
        assert "rollback_probe" not in {
            row[0] for row in db.execute("SHOW TABLES").fetchall()
        }
        assert db.execute("SELECT version FROM _schema_migrations").fetchall() == [(1,)]


def test_unversioned_existing_database_is_not_modified(db_path):
    db_path.parent.mkdir()
    with connect_database(db_path) as db:
        db.execute("CREATE TABLE existing (id INT)")
    with pytest.raises(MigrationError, match="迁移记录"):
        initialize_database(db_path)
    with connect_database(db_path, read_only=True) as db:
        assert db.execute("SHOW TABLES").fetchall() == [("existing",)]


def test_invalid_account_config_rolls_back_first_initialization(db_path, tmp_path):
    config_dir = tmp_path / "config"
    copytree(ROOT / "config", config_dir)
    accounts = config_dir / "accounts.yaml"
    text = accounts.read_text(encoding="utf-8")
    accounts.write_text(text.replace("CORE_PASSIVE", "INVALID_ROLE"), encoding="utf-8")

    with pytest.raises(ValidationError, match="account_role"):
        initialize_database(db_path, config_dir=config_dir)
    with connect_database(db_path, read_only=True) as db:
        assert db.execute("SHOW TABLES").fetchall() == []
    assert initialize_database(db_path) == 1


def test_cli_can_initialize_explicit_path_from_another_working_directory(
    db_path, tmp_path
):
    result = run(
        [executable, str(ROOT / "scripts/init_db.py"), "--db-path", str(db_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert db_path.is_file()
    with connect_database(db_path, read_only=True) as db:
        assert db.execute("SELECT count(*) FROM symbol").fetchone() == (len(SYMBOLS),)
