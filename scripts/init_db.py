import argparse
import sys
from pathlib import Path


def main() -> None:
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from shared.db import DEFAULT_DB_PATH, initialize_database

    parser = argparse.ArgumentParser(description="初始化个人 CIO 的 DuckDB 数据库")
    parser.add_argument(
        "--db-path", type=Path, default=DEFAULT_DB_PATH, help="DuckDB 文件路径"
    )
    path = parser.parse_args().db_path
    version = initialize_database(path)
    print(f"DuckDB 初始化完成（模式版本 {version}）：{path.resolve()}")


if __name__ == "__main__":
    main()
