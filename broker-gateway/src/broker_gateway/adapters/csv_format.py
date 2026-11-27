from dataclasses import dataclass
from typing import Literal

from shared.enums import TransactionType

Section = Literal["transactions", "positions", "cash"]


def label(value: str) -> str:
    return " ".join(value.strip().casefold().split())


@dataclass(frozen=True)
class CsvFormat:
    section: Section
    required: frozenset[str]
    aliases: dict[str, tuple[str, ...]]

    def columns(self, header: list[str]) -> dict[str, list[int]]:
        keys = [label(cell) for cell in header]
        return {
            field: [idx for idx, key in enumerate(keys) if key in names]
            for field, names in self.aliases.items()
            if any(key in names for key in keys)
        }


ACCOUNT = {"source_account": ("account number", "account #", "account id")}
CURRENCY = {"currency": ("currency",)}
IDENTIFIERS = {
    "broker_transaction_id": ("transaction id", "execution id", "trade id"),
    "broker_order_id": ("order id", "order number"),
    "order_type": ("order type",),
    "transaction_time": ("transaction time", "execution time"),
}
CASH = CsvFormat(
    "cash",
    frozenset({"currency"}),
    {
        **ACCOUNT,
        **CURRENCY,
        "cash_balance": ("cash balance",),
        "available_to_trade": ("available to trade", "cash available to trade"),
    },
)

COMMON_TYPES = {
    "buy": TransactionType.BUY,
    "sell": TransactionType.SELL,
    "dividend": TransactionType.DIVIDEND,
    "interest": TransactionType.INTEREST,
    "transfer": TransactionType.TRANSFER,
    "fee": TransactionType.FEE,
    "cash sweep": TransactionType.CASH_SWEEP,
}
