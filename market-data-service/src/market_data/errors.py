from datetime import UTC, date, datetime
from uuid import uuid4

from shared.enums import ErrorType, MessageType


class MarketDataError(Exception):
    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        *,
        suggested_action: str,
        retryable: bool = False,
        symbol: str | None = None,
        trade_date: date | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable
        self.suggested_action = suggested_action
        self.symbol = symbol
        self.trade_date = trade_date

    def to_message(self, *, target: str = "analysis-engine") -> dict:
        return {
            "message_id": f"ERR-{uuid4()}",
            "message_type": MessageType.ERROR.value,
            "source": "market-data-service",
            "target": target,
            "created_at": datetime.now(UTC).isoformat(),
            "symbol": self.symbol,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "payload": {
                "error_type": self.error_type.value,
                "error_message": str(self),
                "retryable": self.retryable,
                "suggested_action": self.suggested_action,
            },
        }


def missing_prices(symbol: str) -> MarketDataError:
    return MarketDataError(
        ErrorType.DATA_MISSING,
        f"{symbol} 在指定区间没有可用日线",
        symbol=symbol,
        suggested_action="检查标的代码、交易日和数据源覆盖范围。",
    )
