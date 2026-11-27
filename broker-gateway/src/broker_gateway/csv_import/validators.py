import re
from datetime import date, datetime
from decimal import Decimal

from shared.enums import ErrorType

_NUMBER = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?\Z")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-/]{0,19}\Z")
_MISSING = {"", "-", "--", "n/a", "na"}


class CsvImportError(ValueError):
    def __init__(
        self,
        code: ErrorType,
        message: str,
        *,
        row: int | None = None,
        committed: bool = False,
    ) -> None:
        self.code = code
        self.row = row
        self.committed = committed
        super().__init__(f"第 {row} 行：{message}" if row is not None else message)


def validation(message: str, row: int | None = None) -> CsvImportError:
    return CsvImportError(ErrorType.VALIDATION_ERROR, message, row=row)


def optional(value: str) -> str | None:
    value = value.strip()
    return None if value.casefold() in _MISSING else value


def number(value: str, field: str, row: int) -> Decimal | None:
    clean = optional(value)
    if clean is None:
        return None
    negative = clean.startswith("(") and clean.endswith(")")
    if negative:
        clean = clean[1:-1].strip()
    elif clean.startswith(("-", "+")):
        negative = clean[0] == "-"
        clean = clean[1:].strip()
    clean = clean.removeprefix("$").strip()
    if not _NUMBER.fullmatch(clean):
        raise validation(f"{field} 不是有效的数字。", row)
    amount = Decimal(clean.replace(",", ""))
    return -amount if negative else amount


def percent(value: str, field: str, row: int) -> float | None:
    clean = optional(value)
    if clean is None:
        return None
    amount = number(clean.removesuffix("%"), field, row)
    if amount is None:
        raise validation(f"{field} 不是有效的百分比。", row)
    return float(amount / 100)


def session_date(value: str, field: str, row: int) -> date | None:
    clean = optional(value)
    if clean is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            pass
    raise validation(f"{field} 不是支持的日期格式。", row)


def timestamp(value: str, field: str, row: int) -> datetime | None:
    clean = optional(value)
    if clean is None:
        return None
    try:
        instant = datetime.fromisoformat(clean)
    except ValueError:
        instant = None
    if instant is None or instant.utcoffset() is None:
        raise validation(f"{field} 必须是含时区的 ISO 时间。", row)
    return instant


def symbol(value: str, row: int) -> str | None:
    clean = optional(value)
    if clean is None:
        return None
    clean = clean.upper()
    if not _SYMBOL.fullmatch(clean):
        raise validation("证券代码不符合首版股票、ETF 或基金格式。", row)
    return clean
