from shared.models import DailySignal


def entry_confidence(signal: DailySignal) -> float | None:
    if signal.confidence is not None:
        return signal.confidence
    if signal.false_breakdown_score is None or signal.volume_confirmation_score is None:
        return None
    return min(signal.false_breakdown_score, signal.volume_confirmation_score)
