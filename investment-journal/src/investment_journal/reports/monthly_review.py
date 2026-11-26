from ..models import PerformanceReview
from .weekly_review import VanguardProgress, render_review


def render_monthly_review(
    review: PerformanceReview, progress: VanguardProgress | None = None
) -> str:
    return render_review("投资月报", review, progress)
