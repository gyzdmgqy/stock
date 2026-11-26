from datetime import date, datetime

from shared.enums import ErrorType

from .errors import MarketDataError


def normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise MarketDataError(
            ErrorType.VALIDATION_ERROR,
            "标的代码不能为空",
            suggested_action="提供数据源支持的标的代码。",
        )
    return symbol.strip().upper()


def validate_dates(symbol: str, start: date, end: date) -> None:
    if (
        not isinstance(start, date)
        or not isinstance(end, date)
        or isinstance(start, datetime)
        or isinstance(end, datetime)
        or start > end
    ):
        raise MarketDataError(
            ErrorType.VALIDATION_ERROR,
            "交易日区间无效",
            symbol=symbol,
            suggested_action="使用日期且起始日期不晚于结束日期。",
        )
