from datetime import UTC, date, datetime
from uuid import uuid4

from shared.enums import ErrorType, MessageType


class AnalysisError(RuntimeError):
    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        *,
        symbol: str | None,
        trade_date: date | None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.symbol = symbol
        self.trade_date = trade_date

    def to_message(self, *, target: str = "trade-planner") -> dict:
        return {
            "message_id": f"ERR-{uuid4()}",
            "message_type": MessageType.ERROR.value,
            "source": "analysis-engine",
            "target": target,
            "created_at": datetime.now(UTC).isoformat(),
            "symbol": self.symbol,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "payload": {
                "error_type": self.error_type.value,
                "error_message": str(self),
                "retryable": False,
                "suggested_action": "检查指定交易日的行情及本地数据库。",
            },
        }
