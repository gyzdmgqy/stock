import json
from pathlib import Path

import yaml
from duckdb import DuckDBPyConnection
from pydantic import BaseModel, ConfigDict, StrictBool, TypeAdapter

from shared.enums import AccountRole, AccountType, Broker, IndividualStockPolicy
from shared.models._types import Fraction, NonBlank

DEFAULT_ETFS = ("SPY", "QQQ", "VOO")
DEFAULT_STOCKS = (
    "MSFT",
    "AAPL",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "VRTX",
    "COST",
    "AVGO",
    "LLY",
)
DEFAULT_WATCHLISTS = (
    "core_index",
    "active_watchlist",
    "long_term_compounders",
    "medical_leaders",
    "ai_leaders",
)


class _SeedAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker: Broker
    account_name: NonBlank | None = None
    account_type: AccountType
    account_role: AccountRole
    individual_stock_policy: IndividualStockPolicy
    order_draft_enabled: StrictBool = False
    api_sync_enabled: StrictBool = False
    csv_import_enabled: StrictBool = True
    default_replacement: dict[NonBlank, Fraction] | None = None
    base_currency: NonBlank = "USD"
    is_active: StrictBool = True


def seed_defaults(db: DuckDBPyConnection, config_dir: Path) -> None:
    raw_accounts = yaml.safe_load(
        (config_dir / "accounts.yaml").read_text(encoding="utf-8")
    )
    accounts = TypeAdapter(dict[NonBlank, _SeedAccount]).validate_python(
        raw_accounts["accounts"]
    )
    watchlists = TypeAdapter(dict[NonBlank, list[NonBlank]]).validate_python(
        yaml.safe_load((config_dir / "symbols.yaml").read_text(encoding="utf-8"))
    )
    symbols = dict.fromkeys(
        (symbol for members in watchlists.values() for symbol in members)
    )
    symbols.update(dict.fromkeys(DEFAULT_ETFS, "ETF"))
    symbols.update(dict.fromkeys(DEFAULT_STOCKS, "STOCK"))
    db.executemany(
        "INSERT INTO symbol (symbol, asset_type) VALUES (?, ?) ON CONFLICT DO NOTHING",
        list(symbols.items()),
    )
    db.executemany(
        "INSERT INTO watchlist (watchlist_id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
        [(name, name) for name in dict.fromkeys((*DEFAULT_WATCHLISTS, *watchlists))],
    )
    members = [
        (name, symbol, priority)
        for name, tickers in watchlists.items()
        for priority, symbol in enumerate(dict.fromkeys(tickers))
    ]
    if members:
        db.executemany(
            """
            INSERT INTO watchlist_symbol (watchlist_id, symbol, priority)
            VALUES (?, ?, ?) ON CONFLICT DO NOTHING
            """,
            members,
        )

    for account_id, account in accounts.items():
        row = account.model_dump(mode="json")
        if account.default_replacement is not None:
            row["default_replacement"] = json.dumps(account.default_replacement)
        db.execute(
            """
            INSERT INTO portfolio_account (
                account_id, broker, account_name, account_type, account_role,
                individual_stock_policy, order_draft_enabled, api_sync_enabled,
                csv_import_enabled, default_replacement, base_currency, is_active
            ) VALUES (
                $account_id, $broker, $account_name, $account_type, $account_role,
                $individual_stock_policy, $order_draft_enabled, $api_sync_enabled,
                $csv_import_enabled, $default_replacement, $base_currency, $is_active
            ) ON CONFLICT DO NOTHING
            """,
            {"account_id": account_id, **row},
        )
