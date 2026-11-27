# ruff: noqa: E402
import argparse
import os
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

if not __package__:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [
        str(root),
        str(root / "broker-gateway/src"),
        str(root / "investment-journal/src"),
    ]

import yaml
from dotenv import dotenv_values
from duckdb import Error as DuckDBError

from broker_gateway.adapters.schwab.read_only import (
    ReadOnlyPolicy,
    SchwabReadClient,
    SchwabReadError,
    TokenMetadata,
)
from broker_gateway.adapters.schwab.sync_service import SchwabSyncService
from shared.db import DEFAULT_DB_PATH, connect_database
from shared.db.database import DEFAULT_CONFIG_DIR, ROOT
from shared.enums import ErrorType

_RUN_KEYS = (
    "SCHWAB_API_ENABLED",
    "ORDER_SUBMISSION_ENABLED",
    "SCHWAB_ACCESS_TOKEN",
    "SCHWAB_ACCESS_TOKEN_EXPIRES_AT",
    "SCHWAB_ACCOUNT_NUMBER",
    "DATABASE_PATH",
)


def _runtime_env() -> dict[str, str]:
    local = dotenv_values(ROOT / ".env", interpolate=False)
    return {
        key: value
        for key in _RUN_KEYS
        if (value := os.environ.get(key, local.get(key))) is not None
    }


def _check_config(config_dir: Path, account_id: str) -> None:
    broker = yaml.safe_load((config_dir / "broker.yaml").read_text(encoding="utf-8"))[
        "brokers"
    ]["schwab"]
    account = yaml.safe_load(
        (config_dir / "accounts.yaml").read_text(encoding="utf-8")
    )["accounts"].get(account_id, {})
    if (
        broker.get("enabled") is not True
        or broker.get("mode") != "read_only"
        or broker.get("order_submission_enabled", False) is not False
        or account.get("broker") != "SCHWAB"
        or account.get("account_role") != "ACTIVE_TRADING"
        or account.get("is_active", True) is not True
        or account.get("base_currency", "USD") != "USD"
        or account.get("api_sync_enabled") is not True
    ):
        raise SchwabReadError(
            ErrorType.RISK_RULE_BLOCKED, "本地券商或账户配置未允许 Schwab 只读同步。"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步已经授权的 Schwab 只读数据")
    parser.add_argument(
        "--confirm-local-acceptance",
        action="store_true",
        help="确认 CSV、日流程和仪表盘已完成本地验收",
    )
    parser.add_argument(
        "--account-id", default="SCHWAB_ROTH", help="本地账户别名，不是券商账号"
    )
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument(
        "--since", type=datetime.fromisoformat, help="读取成交的起点（含时区 ISO 时间）"
    )
    parser.add_argument(
        "--orders", action="store_true", help="一并读取订单状态，须指定 --since"
    )
    args = parser.parse_args(argv)
    if not args.confirm_local_acceptance:
        print("须先完成 CSV、日流程与仪表盘的本地验收。", file=sys.stderr)
        return 1
    try:
        env = _runtime_env()
        policy = ReadOnlyPolicy.from_env(env)
        policy.require_enabled()
        _check_config(args.config_dir, args.account_id)
        path = args.db_path or (
            ROOT / env["DATABASE_PATH"] if env.get("DATABASE_PATH") else DEFAULT_DB_PATH
        )
        if not path.is_file():
            raise SchwabReadError(ErrorType.DATA_MISSING, "找不到已初始化的 DuckDB。")
        auth = TokenMetadata.from_env(env)
        with (
            connect_database(path) as db,
            closing(SchwabReadClient(policy, auth)) as client,
        ):
            result = SchwabSyncService(db, client).sync(
                args.account_id, start=args.since, orders=args.orders
            )
    except SchwabReadError as exc:
        print(f"{exc.code.value}: {exc}", file=sys.stderr)
        return 1
    except (
        DuckDBError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        yaml.YAMLError,
    ):
        print("同步未完成，请检查本地配置、数据库及日志写入状态。", file=sys.stderr)
        return 1
    print(
        f"同步完成。新增持仓 {result.positions_inserted}，现金 {result.cash_inserted}，"
        f"成交 {result.transactions_inserted}；读取订单状态 {len(result.orders)}，"
        f"未支持的持仓 {result.skipped_positions}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
