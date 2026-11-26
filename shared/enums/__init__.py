from __future__ import annotations

from enum import StrEnum, auto


class _CanonicalEnum(StrEnum):
    @staticmethod
    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list
    ) -> str:
        return name


class Broker(_CanonicalEnum):
    SCHWAB = auto()
    VANGUARD = auto()
    MANUAL = auto()


class AccountType(_CanonicalEnum):
    TAXABLE = auto()
    TRADITIONAL_IRA = auto()
    ROTH_IRA = auto()
    OTHER = auto()


class AccountRole(_CanonicalEnum):
    CORE_PASSIVE = auto()
    ACTIVE_TRADING = auto()
    RETIREMENT_INDEX = auto()
    CASH_RESERVE = auto()
    MANUAL = auto()


class IndividualStockPolicy(_CanonicalEnum):
    EXIT_ONLY = auto()
    ACTIVE_ALLOWED = auto()


class Action(_CanonicalEnum):
    HOLD = auto()
    WATCH = auto()
    ADD = auto()
    REDUCE = auto()
    EXIT = auto()
    RE_ENTRY = auto()
    AVOID = auto()
    EXIT_ONLY = auto()


class StrategyType(_CanonicalEnum):
    INDEX_DCA = auto()
    TREND_FOLLOWING = auto()
    RANGE_TRADING = auto()
    FALSE_BREAKDOWN_REENTRY = auto()
    GAP_CONTINUATION = auto()
    GAP_EXHAUSTION_AVOID = auto()
    VANGUARD_EXIT_ONLY = auto()
    ACCOUNT_MIGRATION = auto()
    RISK_REDUCTION = auto()
    EARNINGS_RISK_CONTROL = auto()


class StopType(_CanonicalEnum):
    NONE = auto()
    PRICE_STOP = auto()
    STOP_LIMIT = auto()
    STRUCTURE_CONFIRMATION = auto()
    TIME_STOP = auto()


class OrderType(_CanonicalEnum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()


class OrderInstruction(_CanonicalEnum):
    BUY = auto()
    SELL = auto()


class TimeInForce(_CanonicalEnum):
    DAY = auto()
    GTC = auto()


class Session(_CanonicalEnum):
    NORMAL = auto()
    EXTENDED = auto()


class TradePlanStatus(_CanonicalEnum):
    DRAFT = auto()
    REVIEWED = auto()
    APPROVED = auto()
    REJECTED = auto()
    EXPIRED = auto()
    EXECUTED = auto()

    def allows(self, target: TradePlanStatus) -> bool:
        return target in _PLAN_TRANSITIONS.get(self, ())


class OrderDraftStatus(_CanonicalEnum):
    PENDING_REVIEW = auto()
    APPROVED = auto()
    REJECTED = auto()
    MODIFIED = auto()
    DEFERRED = auto()
    EXPIRED = auto()
    SUBMITTING = auto()
    SUBMITTED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELED = auto()
    FAILED = auto()
    UNKNOWN = auto()

    def allows(self, target: OrderDraftStatus) -> bool:
        return target in _DRAFT_TRANSITIONS.get(self, ())


class ApprovalDecision(_CanonicalEnum):
    APPROVED = auto()
    REJECTED = auto()
    MODIFIED = auto()
    DEFERRED = auto()


class JournalEntryType(_CanonicalEnum):
    DAILY = auto()
    SIGNAL_REVIEW = auto()
    TRADE_PLAN_REVIEW = auto()
    ORDER_REVIEW = auto()
    TRADE_EXECUTION = auto()
    MANUAL_NOTE = auto()
    WEEKLY_REVIEW = auto()
    MONTHLY_REVIEW = auto()
    PERFORMANCE_REVIEW = auto()
    BEHAVIOR_REVIEW = auto()
    ACCOUNT_MIGRATION = auto()


class TransactionType(_CanonicalEnum):
    BUY = auto()
    SELL = auto()
    DIVIDEND = auto()
    TRANSFER = auto()
    FEE = auto()
    INTEREST = auto()
    CASH_SWEEP = auto()
    OTHER = auto()


class TransactionSource(_CanonicalEnum):
    API = auto()
    CSV = auto()
    MANUAL = auto()


class MarketRegime(_CanonicalEnum):
    TREND_UP = auto()
    TREND_DOWN = auto()
    RANGE = auto()
    HIGH_RISK = auto()


class TrendState(_CanonicalEnum):
    STRONG_UP = auto()
    WEAK_UP = auto()
    RANGE = auto()
    WEAK_DOWN = auto()
    STRONG_DOWN = auto()


class PriceLocation(_CanonicalEnum):
    ABOVE_MA200 = auto()
    BELOW_MA200 = auto()
    NEAR_MA200 = auto()


class GapType(_CanonicalEnum):
    NONE = auto()
    BREAKAWAY = auto()
    EXHAUSTION = auto()
    SHAKEOUT = auto()
    PANIC = auto()


class GapDirection(_CanonicalEnum):
    UP = auto()
    DOWN = auto()
    NONE = auto()


class SignalComponent(_CanonicalEnum):
    TREND = auto()
    GAP = auto()
    VOLUME = auto()
    BREAKDOWN = auto()
    RISK = auto()
    FUNDAMENTAL = auto()
    PORTFOLIO = auto()
    EXECUTION = auto()


class ReviewType(_CanonicalEnum):
    WEEKLY = auto()
    MONTHLY = auto()
    QUARTERLY = auto()
    STRATEGY = auto()
    ACCOUNT = auto()
    BEHAVIOR = auto()


class EmotionTag(_CanonicalEnum):
    CALM = auto()
    FEARFUL = auto()
    FOMO = auto()
    FRUSTRATED = auto()
    CONFIDENT = auto()


class OutcomeLabel(_CanonicalEnum):
    WIN = auto()
    LOSS = auto()
    FLAT = auto()
    MISSED_OPPORTUNITY = auto()
    AVOIDED_LOSS = auto()


class ErrorType(_CanonicalEnum):
    DATA_MISSING = auto()
    DATA_STALE = auto()
    AUTH_ERROR = auto()
    BROKER_API_ERROR = auto()
    CSV_PARSE_ERROR = auto()
    VALIDATION_ERROR = auto()
    DUPLICATE_ORDER = auto()
    INSUFFICIENT_CASH = auto()
    INSUFFICIENT_POSITION = auto()
    RISK_RULE_BLOCKED = auto()
    USER_APPROVAL_REQUIRED = auto()
    UNKNOWN = auto()


class MessageType(_CanonicalEnum):
    MARKET_DATA_SNAPSHOT = auto()
    INTRADAY_PRICE_SNAPSHOT = auto()
    DAILY_INDICATOR = auto()
    HOURLY_INDICATOR = auto()
    DAILY_SIGNAL = auto()
    INTRADAY_SIGNAL = auto()
    PORTFOLIO_SNAPSHOT = auto()
    BROKER_TRANSACTION = auto()
    RISK_SNAPSHOT = auto()
    TRADE_PLAN = auto()
    ORDER_DRAFT = auto()
    APPROVAL_DECISION = auto()
    DAILY_CIO_BRIEF = auto()
    JOURNAL_ENTRY = auto()
    PERFORMANCE_REVIEW = auto()
    ERROR = auto()


class IntradayActionHint(_CanonicalEnum):
    WAIT_FOR_LIMIT_ENTRY = auto()


_PLAN_TRANSITIONS = {
    TradePlanStatus.DRAFT: (TradePlanStatus.REVIEWED, TradePlanStatus.EXPIRED),
    TradePlanStatus.REVIEWED: (
        TradePlanStatus.APPROVED,
        TradePlanStatus.REJECTED,
        TradePlanStatus.EXPIRED,
    ),
    TradePlanStatus.APPROVED: (TradePlanStatus.EXECUTED, TradePlanStatus.EXPIRED),
}

_DRAFT_TRANSITIONS = {
    OrderDraftStatus.PENDING_REVIEW: (
        OrderDraftStatus.APPROVED,
        OrderDraftStatus.REJECTED,
        OrderDraftStatus.DEFERRED,
        OrderDraftStatus.MODIFIED,
        OrderDraftStatus.EXPIRED,
    ),
    OrderDraftStatus.DEFERRED: (
        OrderDraftStatus.PENDING_REVIEW,
        OrderDraftStatus.REJECTED,
        OrderDraftStatus.MODIFIED,
        OrderDraftStatus.EXPIRED,
    ),
    OrderDraftStatus.APPROVED: (
        OrderDraftStatus.SUBMITTING,
        OrderDraftStatus.MODIFIED,
        OrderDraftStatus.EXPIRED,
    ),
    OrderDraftStatus.SUBMITTING: (
        OrderDraftStatus.SUBMITTED,
        OrderDraftStatus.REJECTED,
        OrderDraftStatus.FAILED,
        OrderDraftStatus.UNKNOWN,
    ),
    OrderDraftStatus.UNKNOWN: (
        OrderDraftStatus.SUBMITTED,
        OrderDraftStatus.PARTIALLY_FILLED,
        OrderDraftStatus.FILLED,
        OrderDraftStatus.CANCELED,
        OrderDraftStatus.REJECTED,
        OrderDraftStatus.FAILED,
    ),
    OrderDraftStatus.SUBMITTED: (
        OrderDraftStatus.PARTIALLY_FILLED,
        OrderDraftStatus.FILLED,
        OrderDraftStatus.CANCELED,
        OrderDraftStatus.REJECTED,
        OrderDraftStatus.UNKNOWN,
    ),
    OrderDraftStatus.PARTIALLY_FILLED: (
        OrderDraftStatus.PARTIALLY_FILLED,
        OrderDraftStatus.FILLED,
        OrderDraftStatus.CANCELED,
        OrderDraftStatus.UNKNOWN,
    ),
}
