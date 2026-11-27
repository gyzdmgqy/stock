from collections import deque
from collections.abc import Iterable
from typing import Self

from pydantic import ConfigDict, Field, JsonValue, model_validator

from shared.enums import OrderDraftStatus as Status
from shared.models import OrderSnapshot
from shared.models._types import (
    NonBlank,
    PositiveShares,
    Price,
    SharedModel,
    UtcDatetime,
)

_ACCEPTED = {Status.SUBMITTED, Status.PARTIALLY_FILLED, Status.FILLED, Status.CANCELED}


class SimulatedFill(SharedModel):
    model_config = ConfigDict(frozen=True)

    fill_id: NonBlank
    quantity: PositiveShares
    price: Price
    executed_at: UtcDatetime


class SimulatedReply(SharedModel):
    model_config = ConfigDict(frozen=True)

    status: Status
    broker_order_id: NonBlank | None = None
    fills: tuple[SimulatedFill, ...] = ()
    response: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.status not in _ACCEPTED | {
            Status.UNKNOWN,
            Status.REJECTED,
            Status.FAILED,
        }:
            raise ValueError("模拟响应必须使用规范券商结果状态")
        if self.status in _ACCEPTED and self.broker_order_id is None:
            raise ValueError("已接单的模拟凭据必须有订单 ID")
        if self.broker_order_id is not None and not self.broker_order_id.startswith(
            "SIM-"
        ):
            raise ValueError("只接受模拟订单 ID")
        if (
            self.status in (Status.UNKNOWN, Status.FAILED)
            and self.broker_order_id is not None
        ):
            raise ValueError("没有接单证明的响应不能关联订单 ID")
        if self.fills and self.status not in (
            Status.PARTIALLY_FILLED,
            Status.FILLED,
            Status.CANCELED,
        ):
            raise ValueError("该响应状态不能包含成交")
        return self


class SimulationRequest(SharedModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: NonBlank
    draft_id: NonBlank
    order: OrderSnapshot


_ScriptedResult = SimulatedReply | BaseException | None


class SimulatedSchwabAdapter:
    """仅消耗测试脚本提供的预定义结果，不读取网络、OAuth 或认证配置。"""

    def __init__(
        self,
        *,
        initial: Iterable[_ScriptedResult] = (),
        reconciliations: Iterable[_ScriptedResult] = (),
    ) -> None:
        self._initial = deque(initial)
        self._reconciliations = deque(reconciliations)
        self.submissions: list[SimulationRequest] = []
        self.lookups: list[SimulationRequest] = []

    def submit(self, request: SimulationRequest) -> SimulatedReply | None:
        self.submissions.append(request)
        return self._take(self._initial)

    def lookup(self, request: SimulationRequest) -> SimulatedReply | None:
        self.lookups.append(request)
        return self._take(self._reconciliations)

    @staticmethod
    def _take(queue: deque[_ScriptedResult]) -> SimulatedReply | None:
        item = queue.popleft() if queue else None
        if isinstance(item, BaseException):
            raise item
        return item
