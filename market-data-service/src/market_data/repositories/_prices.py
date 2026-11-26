from collections.abc import Iterable
from typing import TypeVar

from duckdb import DuckDBPyConnection, Error
from pydantic import ValidationError

from shared.enums import ErrorType
from shared.models import DailyPrice, IntradayPrice

from .._requests import normalize_symbol
from ..errors import MarketDataError

Price = TypeVar("Price", DailyPrice, IntradayPrice)


def upsert_bars(
    db: DuckDBPyConnection,
    table: str,
    model: type[Price],
    key: tuple[str, ...],
    bars: Iterable[Price],
) -> list[Price]:
    columns = tuple(model.model_fields)
    rows = {}
    for item in bars:
        try:
            bar = model.model_validate(
                {**item.model_dump(), "symbol": normalize_symbol(item.symbol)}
            )
        except (AttributeError, ValidationError) as exc:
            raise MarketDataError(
                ErrorType.VALIDATION_ERROR,
                "待入库的行情记录无效",
                suggested_action="检查行情记录的字段和类型。",
            ) from exc
        rows[tuple(getattr(bar, column) for column in key)] = bar

    if not rows:
        return []

    # 每批用一次 SQL 写入。相同主键取最后一条，已入库行保留创建时间。
    values = [
        value
        for bar in rows.values()
        for value in (getattr(bar, column) for column in columns)
    ]
    names = ", ".join(f'"{column}"' for column in columns)
    conflict_key = ", ".join(f'"{column}"' for column in key)
    placeholders = ", ".join(
        "COALESCE(?, CURRENT_TIMESTAMP)" if column == "created_at" else "?"
        for column in columns
    )
    update = ", ".join(
        f'"{column}" = excluded."{column}"'
        for column in columns
        if column not in key and column != "created_at"
    )
    batches = ", ".join(f"({placeholders})" for _ in rows)
    try:
        db.execute(
            f"INSERT INTO {table} ({names}) VALUES {batches} "
            f"ON CONFLICT ({conflict_key}) DO UPDATE SET {update}",
            values,
        )
    except Error as exc:
        raise _database_error("写入") from exc
    return list(rows.values())


def read_bars(
    db: DuckDBPyConnection, model: type[Price], query: str, params: list
) -> list[Price]:
    try:
        result = db.execute(query, params)
        columns = [column[0] for column in result.description]
        rows = result.fetchall()
    except Error as exc:
        raise _database_error("读取", symbol=params[0]) from exc

    try:
        return [
            model.model_validate(dict(zip(columns, row, strict=True))) for row in rows
        ]
    except ValidationError as exc:
        raise MarketDataError(
            ErrorType.VALIDATION_ERROR,
            "数据库中的行情记录未通过模型校验",
            symbol=params[0],
            suggested_action="检查行情表和当前模型版本。",
        ) from exc


def _database_error(operation: str, *, symbol: str | None = None) -> MarketDataError:
    return MarketDataError(
        ErrorType.UNKNOWN,
        f"DuckDB 行情{operation}失败",
        symbol=symbol,
        suggested_action="检查数据库初始化状态、权限及运行日志。",
    )
