import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from shared.enums import AccountRole, Broker

APP_TIMEZONE = ZoneInfo("America/Chicago")


def canonical(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize() if value else Decimal(0), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"不支持的导入字段类型: {type(value).__name__}")


def digest(value: object) -> str:
    data = json.dumps(
        value,
        default=canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def record_id(prefix: str, account_id: str, *values: object) -> str:
    return f"{prefix}-{digest((account_id, *values))}"


def snapshot_date(observed_at: datetime) -> date:
    return observed_at.astimezone(APP_TIMEZONE).date()


class Account:
    def __init__(self, account_id: str, broker: Broker, role: AccountRole) -> None:
        self.account_id = account_id
        self.broker = broker
        self.role = role
