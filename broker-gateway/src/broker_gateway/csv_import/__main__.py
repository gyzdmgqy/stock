import argparse
import json
import sys
from datetime import datetime
from getpass import getpass
from pathlib import Path

from duckdb import Error as DuckDBError

from shared.db import DEFAULT_DB_PATH, connect_database
from shared.enums import Broker

from . import CsvImportError, CsvImportService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预览并确认导入本地券商 CSV")
    parser.add_argument("broker", choices=(Broker.SCHWAB.value, Broker.VANGUARD.value))
    parser.add_argument("account_id", help="系统中的本地账户 ID")
    parser.add_argument("path", type=Path, help="imports/raw 下的原始 CSV")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="已初始化的 DuckDB"
    )
    parser.add_argument(
        "--observed-at",
        type=datetime.fromisoformat,
        help="持仓或现金观察时间，使用含时区的 ISO 格式",
    )
    parser.add_argument(
        "--verify-source-account",
        action="store_true",
        help="以不回显的方式输入并核对 CSV 中的券商账户号",
    )
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print("请先初始化 DuckDB。", file=sys.stderr)
        return 1
    try:
        source_account = (
            getpass("CSV 上的券商账户号：") if args.verify_source_account else None
        )
        with connect_database(args.db) as db:
            service = CsvImportService(db)
            preview = service.preview(
                args.path,
                broker=Broker(args.broker),
                account_id=args.account_id,
                observed_at=args.observed_at,
                source_account=source_account,
            )
            print(json.dumps(preview.review_payload(), ensure_ascii=False, indent=2))
            if (
                input("核对上方记录后，输入 IMPORT 确认；其他输入取消：").strip()
                != "IMPORT"
            ):
                print("已取消，未写入或移动 CSV。")
                return 0
            result = service.commit(
                preview, confirmation_token=preview.confirmation_token
            )
    except (EOFError, KeyboardInterrupt):
        print("导入操作已中断。请检查归档和入库状态后再重试。", file=sys.stderr)
        return 130
    except CsvImportError as exc:
        print(f"{exc.code.value}: {exc}", file=sys.stderr)
        return 1
    except DuckDBError:
        print("数据库不可用。请确认已初始化，并且没有其他进程在写入。", file=sys.stderr)
        return 1
    print(
        f"已导入：成交及流水 {result.transactions_inserted}，持仓 {result.positions_inserted}，"
        f"现金 {result.cash_inserted}，成交日志 {result.journal_entries_created}；"
        f"跳过已入库记录 {result.duplicates_skipped}。"
    )
    print(f"已归档：{result.archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
