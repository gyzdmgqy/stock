from datetime import datetime

from shared.enums import TransactionSource
from shared.models.portfolio import PortfolioCashSnapshot

from .normalizer import Account, record_id, snapshot_date
from .validators import number, validation


def normalize_cash(
    fields: dict[str, str], row: int, account: Account, observed_at: datetime
) -> PortfolioCashSnapshot:
    values = {
        field: number(fields.get(field, ""), field, row)
        for field in ("cash_balance", "available_to_trade")
    }
    if all(value is None for value in values.values()):
        raise validation("现金行缺少余额和可交易金额。", row)
    return PortfolioCashSnapshot(
        snapshot_id=record_id("CASH", account.account_id, observed_at, values),
        account_id=account.account_id,
        snapshot_date=snapshot_date(observed_at),
        observed_at=observed_at,
        currency="USD",
        source=TransactionSource.CSV,
        **values,
    )
