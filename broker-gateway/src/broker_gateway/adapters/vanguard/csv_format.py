from shared.enums import TransactionType

from ..csv_format import ACCOUNT, COMMON_TYPES, CURRENCY, IDENTIFIERS, CsvFormat

TRANSACTIONS = CsvFormat(
    "transactions",
    frozenset({"trade_date", "action", "symbol"}),
    {
        **ACCOUNT,
        **CURRENCY,
        **IDENTIFIERS,
        "trade_date": ("trade date",),
        "settlement_date": ("settlement date",),
        "action": ("transaction type",),
        "symbol": ("symbol", "ticker"),
        "quantity": ("shares", "quantity"),
        "price": ("share price", "price"),
        "fee": ("commission fees", "commission fee", "fees"),
        "net_amount": ("net amount", "amount"),
        "gross_amount": ("principal amount", "gross amount"),
    },
)
POSITIONS = CsvFormat(
    "positions",
    frozenset({"symbol", "quantity", "market_value"}),
    {
        **ACCOUNT,
        **CURRENCY,
        "symbol": ("symbol", "ticker"),
        "quantity": ("shares",),
        "market_price": ("share price",),
        "market_value": ("total value", "market value"),
        "cost_basis": ("cost basis", "total cost basis"),
        "unrealized_pnl": ("unrealized gain/loss",),
        "unrealized_pnl_percent": ("unrealized gain/loss %",),
    },
)
TYPES = {
    **COMMON_TYPES,
    "reinvestment": TransactionType.BUY,
    "dividend reinvestment": TransactionType.BUY,
    "capital gain reinvestment": TransactionType.BUY,
    "dividend received": TransactionType.DIVIDEND,
    "interest income": TransactionType.INTEREST,
    "transfer in": TransactionType.TRANSFER,
    "transfer out": TransactionType.TRANSFER,
    "sweep in": TransactionType.CASH_SWEEP,
    "sweep out": TransactionType.CASH_SWEEP,
}
CASH_ROWS = {"cash balance"}
TOTAL_ROWS = {"total", "account total"}
