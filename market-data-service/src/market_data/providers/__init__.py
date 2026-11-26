"""行情数据源接口。"""

from datetime import date
from typing import Protocol

from shared.models import DailyPrice


class DailyPriceProvider(Protocol):
    def fetch_daily_prices(
        self, symbol: str, start: date, end: date
    ) -> list[DailyPrice]:
        """返回区间内的日线，起止交易日均计入。"""
        ...
