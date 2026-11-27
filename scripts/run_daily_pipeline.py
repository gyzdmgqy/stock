# ruff: noqa: E402
import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

# 直接运行仓库脚本时，加载各服务的 src 包，无须安装 monorepo 子项目。
if not __package__:
    root = Path(__file__).resolve().parents[1]
    services = (
        "market-data-service",
        "analysis-engine",
        "trade-planner",
        "broker-gateway",
        "personal-cio-agent",
        "investment-journal",
    )
    sys.path[:0] = [str(root), *(str(root / name / "src") for name in services)]

from dotenv import dotenv_values
from duckdb import DuckDBPyConnection
from duckdb import Error as DuckDBError
from pydantic import BaseModel, ValidationError
from yaml import YAMLError

from broker_gateway.drafts import DraftError, OrderDraftService
from investment_journal.services.journal_service import JournalService
from market_data.providers import DailyPriceProvider
from personal_cio_agent.services.brief_service import BriefService
from scripts._daily_pipeline_inputs import PipelineConfig, PortfolioInputs, load_reviews
from scripts._daily_pipeline_market import MarketInputs, session_window
from shared.db import DEFAULT_DB_PATH, connect_database, get_journal_entry
from shared.db.database import DEFAULT_CONFIG_DIR, ROOT
from shared.enums import Action, ErrorType
from shared.models import DailyCioBrief, DailySignal, OrderDraft, TradePlan
from trade_planner.planners.base import PlanningRequest
from trade_planner.rules.hourly_gate import APP_TIMEZONE
from trade_planner.services.trade_plan_service import TradePlanService

DEFAULT_OUTPUT_DIR = ROOT / "outputs"
DEFAULT_PLANNING_INPUTS = ROOT / "imports/normalized/planning.yaml"
_EXECUTABLE = {Action.ADD, Action.RE_ENTRY, Action.REDUCE, Action.EXIT}


@dataclass(frozen=True)
class DailyPipelineResult:
    day: date
    signals: tuple[DailySignal, ...] = ()
    plans: tuple[TradePlan, ...] = ()
    drafts: tuple[OrderDraft, ...] = ()
    brief: DailyCioBrief | None = None
    warnings: tuple[str, ...] = ()
    skipped_reason: str | None = None


def run_daily_pipeline(
    db: DuckDBPyConnection,
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    as_of: datetime | None = None,
    provider: DailyPriceProvider | None = None,
    planning_inputs_path: Path | None = None,
) -> DailyPipelineResult:
    now = datetime.now(UTC) if as_of is None else as_of
    if now.utcoffset() is None:
        raise ValueError("每日流程的评估时刻必须包含时区。")
    now = now.astimezone(UTC)
    config = PipelineConfig.load(config_dir)
    window, skipped = session_window(
        now,
        config.app.market_history_sessions,
        config.limits.block_new_entry_before_earnings_days,
    )
    if window is None:
        return DailyPipelineResult(
            now.astimezone(APP_TIMEZONE).date(), skipped_reason=skipped
        )
    day = window.day
    reviews = load_reviews(planning_inputs_path)
    portfolio = PortfolioInputs(db, config, day, now)
    warnings = portfolio.warnings
    catalog = dict(
        db.execute(
            "SELECT symbol, asset_type FROM symbol WHERE is_active AND currency = 'USD'"
        ).fetchall()
    )
    held = portfolio.held_symbols()
    symbols = tuple(dict.fromkeys((*config.symbols, *held)))
    market = MarketInputs(db, window, provider)
    planner = TradePlanService(db, limits=config.limits)
    gateway = OrderDraftService(db, limits=config.limits)
    signals: list[DailySignal] = []
    plannable: list[DailySignal] = []
    for symbol in symbols:
        if symbol not in catalog:
            warnings.append(f"{symbol}：未在启用的 USD 标的目录中建档，已跳过。")
            continue
        signal, complete, notes = market.analyze(symbol)
        warnings.extend(notes)
        if signal is None:
            continue
        signals.append(signal)
        if complete and catalog[symbol] in ("STOCK", "ETF"):
            plannable.append(signal)

    plans: list[TradePlan] = []
    candidates: list[TradePlan] = []
    for signal in plannable:
        symbol = signal.symbol
        for account_id, account in portfolio.accounts.items():
            if (
                symbol not in config.symbols
                and (account_id, symbol) not in portfolio.positions
            ):
                continue
            state, review, warning = portfolio.for_symbol(
                account_id, symbol, reviews.get((account_id, symbol))
            )
            if warning:
                warnings.append(warning)
            hourly = review.intraday_signal if review else None
            if hourly and not (
                window.current_hours[0] <= hourly.bar_start
                and hourly.bar_start + timedelta(hours=1) <= window.current_hours[1]
            ):
                warnings.append(
                    f"{account_id}/{symbol}：小时确认不在本次常规交易时段。"
                )
                hourly = None
            result = planner.generate_trade_plan(
                PlanningRequest(
                    account_id=account_id,
                    signal_id=signal.signal_id,
                    as_of=now,
                    session_close=window.current_hours[1],
                    trading_sessions=window.sessions,
                    portfolio=state,
                    intraday_signal=hourly,
                    earnings_checked_through=(
                        review.earnings_checked_through if review else None
                    ),
                    entry_prices=review.entry_prices if review else None,
                    exit_limit_price=review.exit_limit_price if review else None,
                    reentry_candidate=review.reentry_candidate if review else False,
                )
            )
            plan = result.plan
            plans.append(plan)
            if result.order_intent is None:
                if plan.action in _EXECUTABLE:
                    warnings.append(
                        f"{account_id}/{symbol}：计划尚无可用的订单参数或账户未开放草稿。"
                    )
                continue
            if not config.drafts_enabled(account_id, account):
                warnings.append(f"{account_id}/{symbol}：账户或券商配置未允许草稿。")
                continue
            candidates.append(plan)

    for plan in candidates:
        try:
            gateway.create_draft(plan.plan_id, as_of=now)
        except DraftError as exc:
            if exc.code is ErrorType.DUPLICATE_ORDER and _draft_ids(
                db, (plan.plan_id,)
            ):
                continue
            warnings.append(f"{plan.account_id}/{plan.symbol}：未生成草稿（{exc}）。")

    plan_ids = tuple(plan.plan_id for plan in plans)
    draft_ids = _draft_ids(db, plan_ids)
    drafts = tuple(gateway.get_draft(identifier) for identifier in draft_ids)
    if any(draft is None for draft in drafts):
        raise RuntimeError("草稿读回失败。")
    warnings = tuple(dict.fromkeys(warnings))
    brief = BriefService(db, output_dir=output_dir / "briefs").generate_daily_brief(
        day,
        as_of=now,
        signal_ids=tuple(signal.signal_id for signal in signals),
        plan_ids=plan_ids,
        warnings=warnings,
    )

    journal = JournalService(db)
    for signal in signals:
        journal.record_signal(signal)
    for plan in plans:
        journal.record_plan(plan)
    for draft in drafts:
        journal.record_draft(draft)
    if draft_ids:
        for (approval_id,) in db.execute(
            "SELECT approval_id FROM approval_record WHERE draft_id IN (SELECT unnest(?)) "
            "AND decided_at <= ? ORDER BY decided_at, approval_id",
            [list(draft_ids), now],
        ).fetchall():
            journal.record_approval(gateway.get_approval(approval_id))
    journal.record_brief(brief)
    entries = tuple(
        get_journal_entry(db, journal_id)
        for (journal_id,) in db.execute(
            "SELECT journal_id FROM journal_entry WHERE journal_date = ? ORDER BY journal_id",
            [day],
        ).fetchall()
    )
    for section, records in (
        ("trade_plans", plans),
        ("order_drafts", drafts),
        ("journal", entries),
    ):
        _write_json(output_dir / section / f"{day.isoformat()}_{section}.json", records)
    return DailyPipelineResult(
        day, tuple(signals), tuple(plans), drafts, brief, warnings
    )


def _draft_ids(db: DuckDBPyConnection, plan_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not plan_ids:
        return ()
    return tuple(
        row[0]
        for row in db.execute(
            "SELECT draft_id FROM order_draft WHERE plan_id IN (SELECT unnest(?)) "
            "ORDER BY created_at, draft_id",
            [list(plan_ids)],
        ).fetchall()
    )


def _write_json(path: Path, records: Sequence[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                [record.model_dump(mode="json") for record in records],
                stream,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行个人 CIO 本地每日流程")
    parser.add_argument("--db-path", type=Path, help="已初始化的 DuckDB 路径")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--planning-inputs", type=Path, help="包含人工确认的本地 YAML")
    parser.add_argument(
        "--offline", action="store_true", help="只读本地行情，不联网补齐"
    )
    args = parser.parse_args(argv)
    try:
        db_path = args.db_path
        if db_path is None:
            configured = os.environ.get("DATABASE_PATH") or dotenv_values(
                ROOT / ".env"
            ).get("DATABASE_PATH")
            db_path = ROOT / configured if configured else DEFAULT_DB_PATH
        if not db_path.is_file():
            print(
                "找不到已初始化的数据库，请先运行 scripts/init_db.py。", file=sys.stderr
            )
            return 1
        provider = None
        if not args.offline:
            from market_data.providers.yfinance_provider import YFinanceProvider

            provider = YFinanceProvider()
        local_inputs = args.planning_inputs
        if local_inputs is None and DEFAULT_PLANNING_INPUTS.is_file():
            local_inputs = DEFAULT_PLANNING_INPUTS
        with connect_database(db_path) as db:
            result = run_daily_pipeline(
                db,
                config_dir=args.config_dir,
                output_dir=args.output_dir,
                provider=provider,
                planning_inputs_path=local_inputs,
            )
    except (ValidationError, YAMLError, KeyError, TypeError):
        print("配置或人工确认文件格式不正确，请核对字段与时间读法。", file=sys.stderr)
        return 1
    except (DuckDBError, OSError, ValueError) as exc:
        print(
            f"每日流程未完成（{type(exc).__name__}）；请检查数据库、文件和运行配置后重试。",
            file=sys.stderr,
        )
        return 1
    if result.skipped_reason:
        print(f"{result.day}：{result.skipped_reason}")
    else:
        print(
            f"{result.day}：信号 {len(result.signals)}，计划 {len(result.plans)}，"
            f"草稿 {len(result.drafts)}，数据提醒 {len(result.warnings)}。"
        )
        print(f"简报：{result.brief.markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
