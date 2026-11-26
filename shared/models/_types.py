from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Score = Annotated[float, Field(ge=0, le=100, strict=True)]
Fraction = Annotated[float, Field(ge=0, le=1, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_as_utc)]
Money = Annotated[Decimal, Field(max_digits=20, decimal_places=6)]
Price = Annotated[Money, Field(gt=0)]
ShareAmount = Annotated[Decimal, Field(max_digits=20, decimal_places=8)]
PositiveShares = Annotated[ShareAmount, Field(gt=0)]


class SharedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, validate_assignment=True
    )


class TimestampedModel(SharedModel):
    created_at: UtcDatetime | None = None


class MutableRecord(TimestampedModel):
    updated_at: UtcDatetime | None = None
