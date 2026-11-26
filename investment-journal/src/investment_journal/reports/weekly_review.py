from dataclasses import dataclass
from datetime import date

from ..models import PerformanceReview

BENCHMARKS = ("VOO", "QQQ", "SPY")


@dataclass(frozen=True)
class VanguardProgress:
    initial_date: date | None = None
    current_date: date | None = None
    initial_stock_count: int | None = None
    current_stock_count: int | None = None
    initial_stock_value: float | None = None
    current_stock_value: float | None = None
    voo_value: float | None = None
    qqq_value: float | None = None

    @property
    def voo_qqq_ratio(self) -> float | None:
        if self.voo_value is not None and self.qqq_value:
            return self.voo_value / self.qqq_value
        return None


def _value(value) -> str:
    return "待确认" if value is None else str(value)


def render_review(
    title: str,
    review: PerformanceReview,
    progress: VanguardProgress | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"{review.period_start} 至 {review.period_end} · {review.account_id or '全部账户'}",
        "",
        "## 计划、决策与成交",
        "",
        f"- 计划版本数 {review.plan_count}",
        f"- 已记录审批通过 {review.approved_count}，拒绝 {review.rejected_count}",
        f"- 买卖成交记录 {review.trade_count}",
    ]
    if progress is not None:
        lines.extend(
            [
                "",
                "## Vanguard 持仓变化",
                "",
                f"- 对比 {_value(progress.initial_date)} 和 {_value(progress.current_date)} 的已观察快照。",
                f"- 个股数量 {_value(progress.initial_stock_count)} → {_value(progress.current_stock_count)}。",
                f"- 个股市值 {_value(progress.initial_stock_value)} → {_value(progress.current_stock_value)}。",
                f"- 最新 VOO / QQQ 市值比 {_value(progress.voo_qqq_ratio)}。",
            ]
        )
    lines.extend(
        [
            "",
            "## 基准比较",
            "",
            "| 基准 | 5 日 | 20 日 | 60 日 |",
            "|---|---|---|---|",
            *(f"| {symbol} | 待接入 | 待接入 | 待接入 |" for symbol in BENCHMARKS),
            "",
            "## 复盘事项",
            "",
            "- 按计划与实际成交分别回看。待填写经验和后续行动。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_weekly_review(
    review: PerformanceReview, progress: VanguardProgress | None = None
) -> str:
    return render_review("投资周报", review, progress)
