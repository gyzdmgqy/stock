from datetime import date

from shared.enums import (
    Action,
    EmotionTag,
    JournalEntryType,
    MarketRegime,
    StrategyType,
)

from ._types import MutableRecord, NonBlank, Score


class JournalEntry(MutableRecord):
    journal_id: NonBlank
    journal_date: date
    entry_type: JournalEntryType
    symbol: NonBlank | None = None
    account_id: NonBlank | None = None
    plan_id: NonBlank | None = None
    draft_id: NonBlank | None = None
    transaction_id: NonBlank | None = None
    action: Action | None = None
    thesis: str | None = None
    decision_reason: str | None = None
    user_note: str | None = None
    system_note: str | None = None
    market_regime: MarketRegime | None = None
    strategy_type: StrategyType | None = None
    confidence: Score | None = None
    emotion_tag: EmotionTag | None = None
    discipline_score: Score | None = None
    outcome_5d: float | None = None
    outcome_20d: float | None = None
    outcome_60d: float | None = None
