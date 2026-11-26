from datetime import date

from shared.enums import ErrorType
from shared.models import DailyPrice

from .._requests import normalize_symbol, validate_dates
from ..errors import MarketDataError, missing_prices
from ..providers import DailyPriceProvider
from ..repositories.daily_price_repository import DailyPriceRepository


class DailyPriceService:
    def __init__(
        self, provider: DailyPriceProvider, repository: DailyPriceRepository
    ) -> None:
        self._provider = provider
        self._repository = repository

    def download_daily_prices(
        self, symbol: str, start: date, end: date
    ) -> list[DailyPrice]:
        symbol = normalize_symbol(symbol)
        validate_dates(symbol, start, end)
        try:
            bars = self._provider.fetch_daily_prices(symbol, start, end)
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError(
                ErrorType.UNKNOWN,
                "行情数据源未能返回日线",
                symbol=symbol,
                suggested_action="检查数据源配置和运行日志。",
            ) from exc

        if not bars:
            raise missing_prices(symbol)

        for bar in bars:
            if (
                not isinstance(bar, DailyPrice)
                or bar.symbol != symbol
                or not start <= bar.trade_date <= end
                or any(
                    getattr(bar, field) is None
                    for field in ("open", "high", "low", "close", "volume")
                )
            ):
                raise MarketDataError(
                    ErrorType.VALIDATION_ERROR,
                    "数据源返回的日线与请求不符或缺少 OHLCV",
                    symbol=symbol,
                    suggested_action="检查数据源的标的、交易日和日线字段。",
                )

        return self._repository.upsert_daily_prices(bars)
