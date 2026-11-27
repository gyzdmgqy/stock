# Personal CIO System
## Investment Journal Design V1.0

---

# 1. Purpose

Phase 6 的接口、日志来源和回看口径见
[投资日志实现说明](../investment-journal/README.md)。

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
- Exit and re-entry variants of TRADE_PLAN

## 4.3 broker-gateway

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

Use JournalEntryType from [doc 04](04_Database_Design.md#canonical-enums-and-status-transitions).

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

Required outcome-tracking table (provisioned in Phase 2; populated in Phase 6):

```text
trade_outcome
```

---

# 8. journal_entry Table

Purpose:

Stores user/system journal entries.

Canonical table definition: [doc 04, journal_entry](04_Database_Design.md#121-journal_entry).
All fields from this document's original richer schema are retained there.

---

# 9. trade_outcome Table

Purpose:

Stores post-trade or post-plan outcome tracking.

A Trade Plan should be evaluated even if it was rejected, because rejected plans can still teach whether the system signal was useful.

Canonical table definition: [doc 04, trade_outcome](04_Database_Design.md#123-trade_outcome).
All fields from this document's original richer schema are retained there.

---

# 10. performance_review Table

Purpose:

Stores aggregated strategy and account review.

Canonical table definition: [doc 04, performance_review](04_Database_Design.md#122-performance_review).
All fields from this document's original richer schema are retained there.

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

首版将计划日普通收盘价作为计划回看的起点，包括被拒绝的计划。成交以每笔成交价
起算，买入后上涨和卖出后下跌为正值。按提供的交易日历取之后的第 5、20、60
个交易日并限制在 `as_of` 以内。目标日缺价时不移到其他日期。缺少中间日价格
只影响路径指标。计划回看和成交回看独立存储并更新对应日志摘要。

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

Group plans/trades by the canonical StrategyType in doc 04.

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

Phase 6 在周报和月报中保留 VOO、QQQ、SPY 的 5、20、60 日占位项，
后续再实现逐窗口超额收益计算。

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

Future schema changes belong in doc 04. Benchmark fields must specify their
5/20/60-trading-day horizon before they are added; Phase 6 uses placeholders.

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

Protective exits are assessed against their own rules, not the entry-confidence
threshold. Do not label a valid low-entry-confidence REDUCE / EXIT as a violation.

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
This month, 3 externally imported entry trades had confidence below the entry threshold.
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

Phase 7 简报的「日志提醒」展示业务日期之前最近五条可用记录，排除由简报生成的日志，避免上一份简报的内容被反复引用。生成简报本身不写入日志；后续流程可通过已有日记服务记录简报事件。

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

These abbreviated model sketches illustrate service usage; doc 04 owns the
complete field set and enum values. They are not independent schema definitions.

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

# 24. Journal Capabilities

[Doc 10](10_TDD_Development_Plan_and_Codex_Prompts.md) owns build sequencing.
Basic journal services and outcome calculations are Phase 6, CSV linking is
integrated in Phase 8, and the daily pipeline in Phase 10. Full performance and
behavioral analytics are follow-on scope unless explicitly added to doc 10.

## Capability: Basic Journal

- Record Daily CIO Brief
- Record Trade Plans
- Record user decisions
- Record manual notes

## Capability: Transaction Linking

- Link broker transactions to plans
- Link order drafts to executions
- Import Schwab/Vanguard transactions

## Capability: Outcome Tracking

- Calculate 5d / 20d / 60d outcomes
- Track max drawdown and max runup
- Compare rejected vs approved plans

## Capability: Performance Review

- Generate weekly review
- Generate monthly review
- Strategy-level performance
- Account-level performance

## Capability: Behavioral Analytics

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
