from pydantic import BaseModel, ConfigDict, Field


class SignalRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    near_ma200_fraction: float = Field(default=0.01, ge=0, lt=1)
    lower_shadow_min: float = Field(default=0.40, gt=0, le=1)
    near_high_fraction: float = Field(default=0.25, gt=0, le=1)
    panic_volume_ratio: float = Field(default=2.0, gt=1)
    material_gap_percent: float = Field(default=0.5, gt=0)


DEFAULT_RULES = SignalRules()
RULE_VERSION = "phase4-v1"
