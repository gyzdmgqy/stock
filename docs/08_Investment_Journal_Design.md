# Personal CIO System
## Investment Journal Design V1.0

---

# 1. Purpose

This document defines the design of the **Investment Journal** module for the Personal CIO System.

The Investment Journal is responsible for recording, auditing, reviewing, and learning from all investment-related activities.

It is not only a diary. It is the system's memory and feedback loop.

The module should help answer:

```text
What did the system recommend?
What did I decide?
What did I actually do?
What happened afterward?
Which strategies worked?
Which strategies failed?
Am I improving over time?
```

---

# 2. Design Philosophy

## 2.1 Journal is the feedback engine

Without journal data, the system cannot improve.

The Investment Journal connects:

```text
Signal
  ↓
Trade Plan
  ↓
Order Draft
  ↓
User Decision
  ↓
Execution
  ↓
Outcome
  ↓
Performance Review
```

---

## 2.2 Record intent, decision, action, and outcome separately

The system must clearly distinguish:

| Layer | Meaning |
|---|---|
| Signal | What the market showed |
| Trade Plan | What the system proposed |
| User Decision | What the user chose |
| Execution | What actually happened |
| Outcome | What happened afterward |

This separation is critical for performance analysis.

Example:

```text
The system suggested WATCH.
The user chased a BUY.
The order filled at a poor price.
The stock fell 8%.
```

The journal should identify whether the loss came from:

- Bad signal
- Bad plan
- Bad user override
- Bad execution
- Bad risk control
- Random market outcome

---

# 3. Scope

## 3.1 In Scope

The Investment Journal records:

- Daily market state
- Daily CIO Brief
- Signals
- Trade Plans
- Order Drafts
- Approval decisions
- Real broker transactions
- Manual notes
- Position snapshots
- Strategy outcomes
- Weekly reviews
- Monthly reviews
- Account-level performance
- Strategy-level performance
- Behavior-level review

---

## 3.2 Out of Scope for MVP

The MVP does not require:

- Tax reporting
- Full performance attribution by factor model
- Multi-user journal
- Real-time trade commentary
- Complex portfolio accounting
- External CRM-like note system

---

# 4. Inputs

The Investment Journal consumes data from:

## 4.1 analysis-engine

- DAILY_SIGNAL
- INTRADAY_SIGNAL
- RISK_SNAPSHOT

## 4.2 trade-planner

- TRADE_PLAN
- EXIT_PLAN
- RE_ENTRY_PLAN

## 4.3 broker-gateway-schwab

- ORDER_DRAFT
- APPROVAL_DECISION
- BROKER_TRANSACTION
- PORTFOLIO_SNAPSHOT

## 4.4 personal-cio-agent

- DAILY_CIO_BRIEF

## 4.5 Manual User Input

- User notes
- Decision rationale
- Emotional state
- Override reason
- Lessons learned

---

# 5. Outputs

The Investment Journal produces:

- Journal Entries
- Daily Logs
- Weekly Review
- Monthly Review
- Strategy Performance Review
- Account Performance Review
- Behavior Review
- Improvement Suggestions

---

# 6. Journal Entry Types

Supported entry types:

```text
DAILY
SIGNAL_REVIEW
TRADE_PLAN_REVIEW
ORDER_REVIEW
TRADE_EXECUTION
MANUAL_NOTE
WEEKLY_REVIEW
MONTHLY_REVIEW
PERFORMANCE_REVIEW
BEHAVIOR_REVIEW
ACCOUNT_MIGRATION
```

---

# 7. Core Tables

The Investment Journal primarily uses the following DuckDB tables:

```text
journal_entry
broker_transaction
trade_plan
order_draft
approval_record
portfolio_position_snapshot
daily_signal
daily_cio_brief
performance_review
```

Additional recommended table:

```text
trade_outcome
```

---

# 8. journal_entry Table

Purpose:

Stores user/system journal entries.

```sql
CREATE TABLE IF NOT EXISTS journal_entry (
    journal_id TEXT PRIMARY KEY,
    journal_date DATE NOT NULL,

    symbol TEXT,
    account_id TEXT,
    plan_id TEXT,
    draft_id TEXT,
    transaction_id TEXT,

    entry_type TEXT,            -- DAILY, TRADE_PLAN_REVIEW, ORDER_REVIEW, etc.
    action TEXT,

    thesis TEXT,
    decision_reason TEXT,
    user_note TEXT,
    system_note TEXT,

    market_regime TEXT,
    strategy_type TEXT,
    confidence DOUBLE,

    emotion_tag TEXT,           -- CALM, FEARFUL, FOMO, FRUSTRATED, CONFIDENT
    discipline_score DOUBLE,    -- 0-100

    outcome_5d DOUBLE,
    outcome_20d DOUBLE,
    outcome_60d DOUBLE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

# 9. trade_outcome Table

Purpose:

Stores post-trade or post-plan outcome tracking.

A Trade Plan should be evaluated even if it was rejected, because rejected plans can still teach whether the system signal was useful.

```sql
CREATE TABLE IF NOT EXISTS trade_outcome (
    outcome_id TEXT PRIMARY KEY,

    plan_id TEXT,
    draft_id TEXT,
    transaction_id TEXT,
    symbol TEXT,
    account_id TEXT,

    reference_date DATE NOT NULL,
    reference_price DOUBLE,

    outcome_date_5d DATE,
    outcome_price_5d DOUBLE,
    outcome_return_5d DOUBLE,
    max_drawdown_5d DOUBLE,
    max_runup_5d DOUBLE,

    outcome_date_20d DATE,
    outcome_price_20d DOUBLE,
    outcome_return_20d DOUBLE,
    max_drawdown_20d DOUBLE,
    max_runup_20d DOUBLE,

    outcome_date_60d DATE,
    outcome_price_60d DOUBLE,
    outcome_return_60d DOUBLE,
    max_drawdown_60d DOUBLE,
    max_runup_60d DOUBLE,

    outcome_label TEXT,          -- WIN, LOSS, FLAT, MISSED_OPPORTUNITY, AVOIDED_LOSS
    lesson TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

# 10. performance_review Table

Purpose:

Stores aggregated strategy and account review.

```sql
CREATE TABLE IF NOT EXISTS performance_review (
    review_id TEXT PRIMARY KEY,
    review_date DATE NOT NULL,

    review_type TEXT,            -- WEEKLY, MONTHLY, QUARTERLY, STRATEGY, ACCOUNT, BEHAVIOR
    strategy_type TEXT,
    account_id TEXT,

    period_start DATE,
    period_end DATE,

    trade_count INTEGER,
    plan_count INTEGER,
    approved_count INTEGER,
    rejected_count INTEGER,

    win_rate DOUBLE,
    average_return DOUBLE,
    median_return DOUBLE,
    max_drawdown DOUBLE,
    average_risk_reward DOUBLE,

    best_trade_symbol TEXT,
    worst_trade_symbol TEXT,

    summary TEXT,
    lessons TEXT,
    next_actions TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 11. Manual Note Schema

Manual notes are important because not all decision context is captured by data.

Example:

```json
{
  "journal_id": "JRN-20260607-MANUAL-001",
  "journal_date": "2026-06-07",
  "entry_type": "MANUAL_NOTE",
  "symbol": "VRTX",
  "user_note": "I felt FOMO after the stock bounced above MA200. Decided not to chase until hourly confirmation.",
  "emotion_tag": "FOMO",
  "discipline_score": 85
}
```

---

# 12. Decision Quality Tracking

The Journal should score decision quality separately from financial outcome.

A good decision can lose money.

A bad decision can make money.

Recommended decision quality fields:

```text
followed_plan
respected_account_role
respected_position_size
respected_stop_logic
avoided_fomo
avoided_panic_sell
decision_quality_score
```

Suggested score interpretation:

```text
0-30: poor discipline
31-60: mixed discipline
61-80: good discipline
81-100: excellent discipline
```

---

# 13. Outcome Evaluation Logic

The system should evaluate outcomes at multiple horizons:

```text
5 trading days
20 trading days
60 trading days
```

For each plan or trade, calculate:

- Forward return
- Max drawdown
- Max runup
- Whether stop would have triggered
- Whether target would have been reached
- Whether rejected plan would have worked
- Whether approved plan worked

---

# 14. Plan vs Execution Analysis

The Journal should compare:

## Planned

- planned entry price
- planned stop price
- planned position size
- planned strategy
- planned invalid condition

## Actual

- actual execution price
- actual quantity
- actual order type
- actual exit price
- actual holding period
- actual outcome

Example insights:

```text
Your limit price was too aggressive and missed several valid entries.
Your stop limit was too tight and caused avoidable exits.
Your rejected plans had positive 20-day forward returns.
Your approved trades worked better when confidence > 75.
```

---

# 15. Account-Level Journal Logic

The Journal should respect account roles.

## Vanguard Roth IRA

Role:

```text
CORE_PASSIVE
```

Journal focus:

- Individual stock exit progress
- VOO / QQQ replacement progress
- Passive core allocation
- No new individual stock buy enforcement
- Long-term compounding tracking

Important review question:

```text
Is Vanguard becoming simpler and more passive over time?
```

## Schwab Roth IRA

Role:

```text
ACTIVE_TRADING
```

Journal focus:

- Active trade performance
- Trade Planner quality
- Order draft quality
- User approval behavior
- Strategy win rate
- Risk control discipline

Important review question:

```text
Is Schwab active trading outperforming VOO / QQQ after risk and effort?
```

---

# 16. Strategy-Level Review

The Journal should group plans/trades by strategy_type:

```text
TREND_FOLLOWING
RANGE_TRADING
FALSE_BREAKDOWN_REENTRY
GAP_CONTINUATION
GAP_EXHAUSTION_AVOID
VANGUARD_EXIT_ONLY
ACCOUNT_MIGRATION
RISK_REDUCTION
EARNINGS_RISK_CONTROL
INDEX_DCA
```

For each strategy, calculate:

- number of plans
- approval rate
- win rate
- average 5d return
- average 20d return
- average 60d return
- max drawdown
- best symbol
- worst symbol
- notes

---

# 17. Benchmark Comparison

The Journal should compare active decisions against benchmarks.

Recommended benchmarks:

```text
VOO
QQQ
SPY
```

Examples:

```text
Schwab active trading vs QQQ
Schwab active trading vs VOO
Vanguard passive core vs VOO/QQQ blend
Individual trades vs QQQ forward return
```

For every trade outcome, compute:

```text
excess_return_vs_voo
excess_return_vs_qqq
excess_return_vs_spy
```

Future schema extension:

```sql
ALTER TABLE trade_outcome ADD COLUMN excess_return_vs_voo DOUBLE;
ALTER TABLE trade_outcome ADD COLUMN excess_return_vs_qqq DOUBLE;
ALTER TABLE trade_outcome ADD COLUMN excess_return_vs_spy DOUBLE;
```

---

# 18. Weekly Review

Weekly review should answer:

```text
What happened this week?
What did the system recommend?
What did I approve or reject?
What did I override?
Did I follow my rules?
Which plans are still active?
Which trades need follow-up?
```

Recommended weekly report sections:

1. Market Summary
2. Portfolio Summary
3. Plans Generated
4. Orders Approved / Rejected
5. Trades Executed
6. Rule Violations
7. Best Decision
8. Worst Decision
9. Lessons Learned
10. Next Week Focus

---

# 19. Monthly Review

Monthly review should answer:

```text
Is the system improving my investment process?
Is Schwab active trading worth the effort?
Is Vanguard becoming a clean passive core account?
Which strategies deserve more capital?
Which strategies should be reduced or removed?
```

Recommended monthly report sections:

1. Total Portfolio Overview
2. Vanguard Core Passive Progress
3. Schwab Active Trading Performance
4. Strategy Performance
5. Benchmark Comparison
6. Behavioral Review
7. Account Role Compliance
8. Lessons Learned
9. System Improvement Tasks

---

# 20. Behavior Review

Behavior review tracks whether the user is improving as an investor.

Important behavior metrics:

- FOMO trades
- Panic sells
- Plan violations
- Oversized positions
- Trades before earnings
- Stop overrides
- Late exits
- Missed planned entries
- Rejected good plans
- Approved weak plans

Example output:

```text
This month, 3 trades were approved below confidence threshold.
2 trades were influenced by FOMO.
You followed account-role rules 100% of the time.
You avoided new individual stock buys in Vanguard.
```

---

# 21. Journal Report Output

Reports should be generated in Markdown.

Recommended folder:

```text
outputs/journal/
├── daily/
├── weekly/
├── monthly/
└── strategy/
```

Example files:

```text
outputs/journal/daily/2026-06-07_journal.md
outputs/journal/weekly/2026-W23_review.md
outputs/journal/monthly/2026-06_review.md
```

---

# 22. Integration with Daily CIO Brief

The Daily CIO Brief should include a small Journal section.

Example:

```markdown
## Journal Reminder

- Yesterday's VRTX WATCH plan remains active.
- No order was approved.
- You avoided chasing a weak rebound.
- Follow-up needed: check volume confirmation tomorrow.
```

---

# 23. Pydantic Model Draft

```python
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class JournalEntry(BaseModel):
    journal_id: str
    journal_date: date
    symbol: Optional[str] = None
    account_id: Optional[str] = None
    plan_id: Optional[str] = None
    draft_id: Optional[str] = None
    transaction_id: Optional[str] = None
    entry_type: str
    action: Optional[str] = None
    thesis: Optional[str] = None
    decision_reason: Optional[str] = None
    user_note: Optional[str] = None
    system_note: Optional[str] = None
    market_regime: Optional[str] = None
    strategy_type: Optional[str] = None
    confidence: Optional[float] = None
    emotion_tag: Optional[str] = None
    discipline_score: Optional[float] = None
    outcome_5d: Optional[float] = None
    outcome_20d: Optional[float] = None
    outcome_60d: Optional[float] = None


class TradeOutcome(BaseModel):
    outcome_id: str
    plan_id: Optional[str] = None
    draft_id: Optional[str] = None
    transaction_id: Optional[str] = None
    symbol: str
    account_id: Optional[str] = None
    reference_date: date
    reference_price: float
    outcome_return_5d: Optional[float] = None
    outcome_return_20d: Optional[float] = None
    outcome_return_60d: Optional[float] = None
    max_drawdown_20d: Optional[float] = None
    max_runup_20d: Optional[float] = None
    outcome_label: Optional[str] = None
    lesson: Optional[str] = None


class PerformanceReview(BaseModel):
    review_id: str
    review_date: date
    review_type: str
    strategy_type: Optional[str] = None
    account_id: Optional[str] = None
    period_start: date
    period_end: date
    trade_count: int = 0
    plan_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    win_rate: Optional[float] = None
    average_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    summary: Optional[str] = None
    lessons: Optional[str] = None
    next_actions: Optional[str] = None
```

---

# 24. Development Phases

## Phase 1: Basic Journal

- Record Daily CIO Brief
- Record Trade Plans
- Record user decisions
- Record manual notes

## Phase 2: Transaction Linking

- Link broker transactions to plans
- Link order drafts to executions
- Import Schwab/Vanguard transactions

## Phase 3: Outcome Tracking

- Calculate 5d / 20d / 60d outcomes
- Track max drawdown and max runup
- Compare rejected vs approved plans

## Phase 4: Performance Review

- Generate weekly review
- Generate monthly review
- Strategy-level performance
- Account-level performance

## Phase 5: Behavioral Analytics

- Detect FOMO trades
- Detect rule violations
- Detect plan drift
- Recommend system/rule improvements

---

# 25. Testing Strategy

## Unit Tests

Test:

- Journal entry creation
- Outcome calculation
- Benchmark comparison
- Strategy grouping
- Discipline score calculation
- Report generation

## Integration Tests

Test:

- Trade Plan -> Journal Entry
- Approval -> Journal Entry
- Broker Transaction -> Trade Outcome
- Daily CIO Brief -> Daily Journal
- Weekly review generation

## Regression Tests

Ensure:

- Historical journal records are never overwritten incorrectly
- Outcome metrics are reproducible
- Strategy statistics match source trades
- Reports can be regenerated

---

# 26. Success Criteria

The Investment Journal is successful if it can answer:

```text
What did the system recommend?
What did I approve?
What did I reject?
What did I actually trade?
What was the outcome?
Did I follow my rules?
Which strategies worked?
Which strategies failed?
Is Schwab active trading outperforming VOO/QQQ?
Is Vanguard becoming a clean passive core account?
What should I improve next month?
```

The Journal should turn investing from a series of isolated decisions into a measurable, reviewable, continuously improving process.
