import json
from enum import StrEnum

from duckdb import DuckDBPyConnection

from shared.models import JournalEntry, TradePlan

_NESTED_PLAN_FIELDS = {
    "entry_order": {
        "type": "entry_order_type",
        "price": "entry_price",
    },
    "stop_order": {
        "type": "stop_type",
        "stop_price": "stop_price",
        "limit_price": "stop_limit_price",
        "condition": "stop_condition",
        "reason": "stop_reason",
    },
    "position_size": {
        "percent_of_portfolio": "position_size_percent",
        "estimated_value": "position_size_value",
        "quantity": "quantity",
        "sizing_basis": "sizing_basis",
        "sizing_base_value": "sizing_base_value",
    },
}
_PLAN_JSON_FIELDS = (
    "input_references",
    "entry_condition",
    "invalid_condition",
    "exit_trigger",
    "replacement",
)
_PLAN_COLUMNS = (
    *(field for field in TradePlan.model_fields if field not in _NESTED_PLAN_FIELDS),
    *(column for fields in _NESTED_PLAN_FIELDS.values() for column in fields.values()),
)
_JOURNAL_COLUMNS = tuple(JournalEntry.model_fields)


def _insert(db: DuckDBPyConnection, table: str, row: dict) -> None:
    # 表名与列名来自模块常量和模型字段，输入值使用 SQL 参数。
    if row.get("created_at") is None:
        row.pop("created_at", None)
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    values = [
        value.value if isinstance(value, StrEnum) else value for value in row.values()
    ]
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)


def _find(
    db: DuckDBPyConnection,
    table: str,
    columns: tuple[str, ...],
    key: str,
    value: str,
) -> dict | None:
    row = db.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {key} = ?", [value]
    ).fetchone()
    return None if row is None else dict(zip(columns, row, strict=True))


def _require_reference(
    db: DuckDBPyConnection,
    table: str,
    key: str,
    value: str,
    columns: tuple[str, ...],
) -> dict:
    record = _find(db, table, columns, key, value)
    if record is None:
        raise ValueError(f"{key} 引用不存在：{value}")
    return record


def _merge_links(links: dict, reference: dict) -> None:
    for key, value in reference.items():
        if value is not None:
            if links.get(key) not in (None, value):
                raise ValueError(f"关联记录的 {key} 不一致")
            links[key] = value


def insert_trade_plan(db: DuckDBPyConnection, plan: TradePlan) -> None:
    plan = TradePlan.model_validate(plan.model_dump())
    _require_reference(db, "symbol", "symbol", plan.symbol, ("symbol",))
    _require_reference(
        db, "portfolio_account", "account_id", plan.account_id, ("account_id",)
    )
    if plan.future_reentry_account is not None:
        _require_reference(
            db,
            "portfolio_account",
            "account_id",
            plan.future_reentry_account,
            ("account_id",),
        )
    if plan.supersedes_plan_id is not None:
        previous = _require_reference(
            db,
            "trade_plan",
            "plan_id",
            plan.supersedes_plan_id,
            ("account_id", "symbol"),
        )
        _merge_links({"account_id": plan.account_id, "symbol": plan.symbol}, previous)

    row = plan.model_dump()
    for field, mapping in _NESTED_PLAN_FIELDS.items():
        nested = row.pop(field)
        for name, column in mapping.items():
            row[column] = None if nested is None else nested[name]
    for field in _PLAN_JSON_FIELDS:
        if row[field] is not None:
            row[field] = json.dumps(row[field], ensure_ascii=False, allow_nan=False)
    _insert(db, "trade_plan", row)


def get_trade_plan(db: DuckDBPyConnection, plan_id: str) -> TradePlan | None:
    row = _find(db, "trade_plan", _PLAN_COLUMNS, "plan_id", plan_id)
    if row is None:
        return None

    for field, mapping in _NESTED_PLAN_FIELDS.items():
        nested = {name: row.pop(column) for name, column in mapping.items()}
        row[field] = (
            nested if any(value is not None for value in nested.values()) else None
        )
    for field in _PLAN_JSON_FIELDS:
        if row[field] is not None:
            row[field] = json.loads(row[field])
    return TradePlan.model_validate(row)


def insert_journal_entry(db: DuckDBPyConnection, journal: JournalEntry) -> None:
    journal = JournalEntry.model_validate(journal.model_dump())
    links = {
        "account_id": journal.account_id,
        "symbol": journal.symbol,
        "plan_id": journal.plan_id,
        "draft_id": journal.draft_id,
    }
    account_and_symbol = ("account_id", "symbol")
    if journal.transaction_id is not None:
        _merge_links(
            links,
            _require_reference(
                db,
                "broker_transaction",
                "transaction_id",
                journal.transaction_id,
                (*account_and_symbol, "plan_id", "draft_id"),
            ),
        )
    if links["draft_id"] is not None:
        _merge_links(
            links,
            _require_reference(
                db,
                "order_draft",
                "draft_id",
                links["draft_id"],
                (*account_and_symbol, "plan_id"),
            ),
        )
    if links["plan_id"] is not None:
        _merge_links(
            links,
            _require_reference(
                db, "trade_plan", "plan_id", links["plan_id"], account_and_symbol
            ),
        )
    if links["account_id"] is not None:
        _require_reference(
            db, "portfolio_account", "account_id", links["account_id"], ("account_id",)
        )
    if links["symbol"] is not None:
        _require_reference(db, "symbol", "symbol", links["symbol"], ("symbol",))
    _insert(db, "journal_entry", journal.model_dump())


def get_journal_entry(db: DuckDBPyConnection, journal_id: str) -> JournalEntry | None:
    row = _find(db, "journal_entry", _JOURNAL_COLUMNS, "journal_id", journal_id)
    return None if row is None else JournalEntry.model_validate(row)
