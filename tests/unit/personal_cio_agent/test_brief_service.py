import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from personal_cio_agent.services.brief_service import BriefService
from shared.db import connect_database, initialize_database
from shared.models import DailyCioBrief

DAY = date(2026, 6, 5)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "brief.duckdb"
    initialize_database(path)
    with connect_database(path) as connection:
        yield connection


def add_signal(db, signal_id, symbol, day, regime, confidence, reason, created_at):
    db.execute(
        """
        INSERT INTO daily_signal (signal_id, symbol, trade_date, market_regime, confidence, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, CAST(? AS TIMESTAMPTZ))
        """,
        [signal_id, symbol, day, regime, confidence, reason, created_at],
    )


def add_plan(db, plan_id, day, action, status, created_at):
    db.execute(
        """
        INSERT INTO trade_plan (plan_id, symbol, plan_date, account_id, account_role, action, status, confidence, created_at)
        VALUES (?, 'VRTX', ?, 'SCHWAB_ROTH', 'ACTIVE_TRADING', ?, ?, 80, CAST(? AS TIMESTAMPTZ))
        """,
        [plan_id, day, action, status, created_at],
    )


def add_draft(db, draft_id, plan_id, status="PENDING_REVIEW"):
    db.execute(
        "INSERT INTO order_draft (draft_id, plan_id, broker, account_id, symbol, status) "
        "VALUES (?, ?, 'SCHWAB', 'SCHWAB_ROTH', 'VRTX', ?)",
        [draft_id, plan_id, status],
    )


def add_snapshot(db, snapshot_id, day, account, equity, score=None, notes=None):
    db.execute(
        """
        INSERT INTO portfolio_risk_snapshot (
            snapshot_id, snapshot_date, account_id, total_market_value, portfolio_risk_score, notes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [snapshot_id, day, account, equity, score, notes],
    )


def add_note(db, journal_id, day, note, entry_type="MANUAL_NOTE"):
    db.execute(
        "INSERT INTO journal_entry (journal_id, journal_date, entry_type, symbol, user_note) "
        "VALUES (?, ?, ?, 'VRTX', ?)",
        [journal_id, day, entry_type, note],
    )


def test_daily_brief_has_all_sections_and_matches_database_and_exports(db, tmp_path):
    add_signal(
        db,
        "SIG-SPY",
        "SPY",
        DAY,
        "TREND_UP",
        82,
        "SPY 维持上行",
        "2026-06-05T20:00:00Z",
    )
    add_signal(
        db, "SIG-QQQ", "QQQ", DAY, "RANGE", 70, "QQQ 区间波动", "2026-06-05T20:00:00Z"
    )
    add_snapshot(db, "P-ALL", DAY, None, 1200.25, 42, "关注板块集中度")
    add_snapshot(db, "P-VG", DAY, "VANGUARD_ROTH", 500)
    add_snapshot(db, "P-SC", DAY, "SCHWAB_ROTH", 700.25)
    db.execute(
        "INSERT INTO portfolio_position_snapshot (snapshot_id, account_id, snapshot_date, symbol, market_value, quantity) "
        "VALUES ('POS-VRTX', 'SCHWAB_ROTH', ?, 'VRTX', 200.25, 2)",
        [DAY],
    )
    add_plan(db, "TP-1", DAY, "RE_ENTRY", "REVIEWED", "2026-06-05T21:00:00Z")
    add_draft(db, "OD-1", "TP-1")
    add_note(db, "JRN-1", DAY - timedelta(days=1), "核对量能")

    output = tmp_path / "briefs"
    service = BriefService(db, output_dir=output)
    result = service.generate_daily_brief(DAY)
    assert result.brief_id == "BRIEF-20260605"
    assert result.market_summary.market_regime == "TREND_UP"
    assert result.market_summary.confidence == 82
    assert result.portfolio_summary.total_value == Decimal("1200.25")
    assert result.portfolio_summary.core_passive_value == Decimal(500)
    assert result.portfolio_summary.active_trading_value == Decimal("700.25")
    assert result.portfolio_summary.key_positions[0]["symbol"] == "VRTX"
    assert any("关注板块集中度" in item for item in result.risk_summary.key_risks)
    assert any("42" in item for item in result.risk_summary.key_risks)
    assert result.trade_plan_summary[0].plan_id == "TP-1"
    assert result.trade_plan_summary[0].account_id == "SCHWAB_ROTH"
    assert result.order_draft_summary[0].draft_id == "OD-1"
    assert any("核对量能" in item for item in result.journal_reminders)
    assert "1 张待审草稿" in result.final_recommendation

    markdown = output / "2026-06-05_Daily_CIO_Brief.md"
    payload = markdown.with_suffix(".json")
    assert result.markdown_path == str(markdown)
    body = markdown.read_text(encoding="utf-8")
    for section in (
        "市场概览",
        "组合概览",
        "风险提示",
        "交易计划",
        "订单草稿",
        "日志提醒",
        "最终建议",
    ):
        assert f"## {section}" in body
    assert all(item in body for item in ("1,200.25", "TP-1", "OD-1", "核对量能"))
    assert (
        DailyCioBrief.model_validate_json(payload.read_text(encoding="utf-8")) == result
    )
    assert service.get_daily_brief(DAY) == result
    assert db.execute(
        "SELECT json_extract_string(market_summary, '$.market_regime'), markdown_path "
        "FROM daily_cio_brief"
    ).fetchone() == ("TREND_UP", str(markdown))


def test_missing_current_market_and_partial_portfolio_remain_unknown(db, tmp_path):
    yesterday = DAY - timedelta(days=1)
    add_signal(
        db,
        "SIG-OLD",
        "SPY",
        yesterday,
        "HIGH_RISK",
        95,
        "昨天数据",
        "2026-06-04T20:00:00Z",
    )
    add_snapshot(db, "OLD-ALL", yesterday, None, 900, 90, "旧风险")
    add_snapshot(db, "NEW-VG", DAY, "VANGUARD_ROTH", 0)

    result = BriefService(db, output_dir=tmp_path).generate_daily_brief(DAY)
    assert result.market_summary.market_regime is None
    assert result.market_summary.confidence is None
    assert result.portfolio_summary.total_value is None
    assert result.portfolio_summary.core_passive_value == Decimal(0)
    assert result.portfolio_summary.active_trading_value is None
    assert result.risk_summary.risk_level is None
    assert not any("旧风险" in item for item in result.risk_summary.key_risks)
    assert any("缺少" in item for item in result.risk_summary.key_risks)
    assert "补齐" in result.final_recommendation
    assert result.trade_plan_summary == []
    assert result.order_draft_summary == []


def test_latest_versions_and_prior_journal_are_selected_without_circular_reminders(
    db, tmp_path
):
    add_signal(db, "OLD", "SPY", DAY, "TREND_DOWN", 40, None, "2026-06-05T20:00:00Z")
    add_signal(db, "NEW", "SPY", DAY, "RANGE", 75, None, "2026-06-05T21:00:00Z")
    add_signal(
        db,
        "FUTURE",
        "SPY",
        DAY + timedelta(days=1),
        "TREND_UP",
        100,
        None,
        "2026-06-06T21:00:00Z",
    )
    add_snapshot(db, "P-VG", DAY, "VANGUARD_ROTH", 500)
    add_snapshot(db, "P-SC", DAY, "SCHWAB_ROTH", 600)
    add_plan(db, "TP-OLD", DAY, "ADD", "DRAFT", "2026-06-05T20:00:00Z")
    add_plan(db, "TP-NEW", DAY, "WATCH", "DRAFT", "2026-06-05T21:00:00Z")
    add_draft(db, "OD-OLD", "TP-OLD")
    add_note(db, "PAST-NOTE", DAY - timedelta(days=1), "保留提醒")
    add_note(db, "TODAY", DAY, "本轮日志")
    add_note(db, "JRN-BRIEF-OLD", DAY - timedelta(days=1), "昨天简报", "DAILY")

    result = BriefService(db, output_dir=tmp_path).generate_daily_brief(DAY)
    assert result.market_summary.market_regime == "RANGE"
    assert result.portfolio_summary.total_value == Decimal(1100)
    assert [plan.plan_id for plan in result.trade_plan_summary] == ["TP-NEW"]
    assert result.order_draft_summary == []
    assert len(result.journal_reminders) == 1
    assert "保留提醒" in result.journal_reminders[0]
    assert "观察" in result.final_recommendation


def test_same_day_regeneration_is_stable_and_replaces_the_existing_record(db, tmp_path):
    service = BriefService(db, output_dir=tmp_path)
    first = service.generate_daily_brief(DAY)
    original = (tmp_path / "2026-06-05_Daily_CIO_Brief.json").read_bytes()
    assert service.generate_daily_brief(DAY) == first
    assert (tmp_path / "2026-06-05_Daily_CIO_Brief.json").read_bytes() == original
    add_signal(db, "NEW", "SPY", DAY, "RANGE", 0, "新修订", "2026-06-05T20:00:00Z")
    refreshed = service.generate_daily_brief(DAY)
    assert refreshed.brief_id == first.brief_id
    assert refreshed.created_at == first.created_at
    assert refreshed.market_summary.confidence == 0
    assert db.execute("SELECT count(*) FROM daily_cio_brief").fetchone() == (1,)
    assert service.get_daily_brief(DAY) == refreshed
    assert (
        json.loads(
            (tmp_path / "2026-06-05_Daily_CIO_Brief.json").read_text(encoding="utf-8")
        )["market_summary"]["confidence"]
        == 0
    )


def test_failed_file_staging_leaves_previous_database_record_intact(db, tmp_path):
    service = BriefService(db, output_dir=tmp_path)
    first = service.generate_daily_brief(DAY)
    file = tmp_path / "not-a-directory"
    file.write_text("不能覆盖", encoding="utf-8")
    add_signal(db, "NEW", "SPY", DAY, "RANGE", 50, None, "2026-06-05T20:00:00Z")
    with pytest.raises(OSError):
        BriefService(db, output_dir=file).generate_daily_brief(DAY)
    assert service.get_daily_brief(DAY) == first
    assert file.read_text(encoding="utf-8") == "不能覆盖"


def test_conflicting_draft_account_requests_reconciliation(db, tmp_path):
    add_signal(db, "SPY", "SPY", DAY, "TREND_UP", 80, None, "2026-06-05T20:00:00Z")
    add_snapshot(db, "P-ALL", DAY, None, 1000)
    add_plan(db, "TP-1", DAY, "RE_ENTRY", "DRAFT", "2026-06-05T21:00:00Z")
    add_draft(db, "OD-1", "TP-1")
    db.execute(
        "UPDATE order_draft SET account_id = 'VANGUARD_ROTH' WHERE draft_id = 'OD-1'"
    )

    result = BriefService(db, output_dir=tmp_path).generate_daily_brief(DAY)
    assert result.order_draft_summary[0].draft_id == "OD-1"
    assert "关联不一致" in result.final_recommendation
    assert "待审草稿" not in result.final_recommendation


def test_markdown_escapes_journal_markup_but_json_keeps_the_note(db, tmp_path):
    note = "<script>alert(1)</script> | [跟进](https://example.test)\n## 自定义标题"
    add_note(db, "JRN-1", DAY - timedelta(days=1), note)
    result = BriefService(db, output_dir=tmp_path).generate_daily_brief(DAY)
    assert note in result.journal_reminders[0]
    markdown = (tmp_path / "2026-06-05_Daily_CIO_Brief.md").read_text(encoding="utf-8")
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "\\| \\[跟进\\]" in markdown
    assert "\n## 自定义标题" not in markdown
