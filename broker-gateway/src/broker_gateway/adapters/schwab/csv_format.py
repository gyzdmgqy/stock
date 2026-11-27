from shared.enums import TransactionType

from ..csv_format import ACCOUNT, COMMON_TYPES, CURRENCY, IDENTIFIERS, CsvFormat

TRANSACTIONS = CsvFormat(
    "transactions",
    frozenset({"trade_date", "action", "symbol"}),
    {
        **ACCOUNT,
        **CURRENCY,
        **IDENTIFIERS,
        "trade_date": ("date", "trade date"),
        "settlement_date": ("settlement date",),
        "action": ("action",),
        "symbol": ("symbol",),
        "quantity": ("quantity", "qty"),
        "price": ("price",),
        "fee": ("fees & comm", "fees & commissions"),
        "net_amount": ("amount", "net amount"),
        "gross_amount": ("gross amount",),
    },
)
POSITIONS = CsvFormat(
    "positions",
    frozenset({"symbol", "quantity", "market_value"}),
    {
        **ACCOUNT,
        **CURRENCY,
        "symbol": ("symbol",),
        "quantity": ("qty (quantity)", "quantity", "qty"),
        "market_price": ("price",),
        "market_value": ("mkt val (market value)", "market value", "mkt val"),
        "cost_basis": ("cost basis",),
        "unrealized_pnl": ("gain $", "gain/loss $", "unrealized gain/loss"),
        "unrealized_pnl_percent": ("gain %", "gain/loss %"),
        "portfolio_weight": ("% of acct", "% of account"),
        "security_type": ("security type",),
    },
)
TYPES = {
    **COMMON_TYPES,
    "reinvest shares": TransactionType.BUY,
    "reinvest dividend": TransactionType.DIVIDEND,
    "cash dividend": TransactionType.DIVIDEND,
    "qualified dividend": TransactionType.DIVIDEND,
    "bank interest": TransactionType.INTEREST,
    "journal": TransactionType.TRANSFER,
    "moneylink transfer": TransactionType.TRANSFER,
    "account transfer": TransactionType.TRANSFER,
    "bank sweep": TransactionType.CASH_SWEEP,
    "bank sweep in": TransactionType.CASH_SWEEP,
    "bank sweep out": TransactionType.CASH_SWEEP,
}
CASH_ROWS = {"cash & cash investments", "cash and cash investments"}
TOTAL_ROWS = {"account total", "total"}
