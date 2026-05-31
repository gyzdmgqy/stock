# Personal CIO System
## Database Design V1.0

---

# 1. Purpose

This document defines the MVP database design for Personal CIO System.

The MVP database uses **DuckDB only**.

DuckDB is used as the single local analytical database for:

- Market data
- Technical indicators
- Signals
- Trade plans
- Order drafts
- Daily CIO briefs
- Investment journal
- Backtest results

The goal is to keep the MVP simple, local, auditable, and easy to query.

---

# 2. Database Strategy

## 2.1 MVP Decision

Use one DuckDB database file:

```text
data/db/personal_cio.duckdb
```

## 2.2 Why DuckDB for MVP

Personal CIO System is analysis-heavy.

The system needs to:

- Scan historical market data
- Calculate indicators
- Run signal detection
- Compare multiple symbols
- Generate portfolio-level reports
- Run backtests
- Produce Daily CIO Briefs

These workloads are closer to local analytical processing than traditional transactional application storage.

## 2.3 Future Evolution

MVP:

```text
DuckDB only
```

Future:

```text
DuckDB for analytics
SQLite/PostgreSQL for app state and broker workflow
```

---

# 3. Database File Layout

```text
personal-cio-system/
└── data/
    └── db/
        └── personal_cio.duckdb
```

Optional exports:

```text
data/
├── market/
├── signals/
├── trade_plans/
├── reports/
└── journal/
```

---

# 4. Core Entity Relationship

```text
symbol
  ↓
daily_price
  ↓
daily_indicator
  ↓
daily_signal
  ↓
trade_plan
  ↓
order_draft
  ↓
approval_record
  ↓
journal_entry
```

Portfolio-related tables:

```text
portfolio_account
  ↓
portfolio_position_snapshot
  ↓
portfolio_risk_snapshot
```

Report-related tables:

```text
daily_cio_brief
```

Backtest-related tables:

```text
backtest_run
  ↓
backtest_trade
  ↓
backtest_metric
```

---

# 5. Table Design

---

## 5.1 symbol

Stores all tradable and observable symbols.

```sql
CREATE TABLE IF NOT EXISTS symbol (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    asset_type TEXT,          -- STOCK, ETF, INDEX, CASH
    sector TEXT,
    industry TEXT,
    exchange TEXT,
    currency TEXT DEFAULT 'USD',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

Example symbols:

```text
SPY
QQQ
VRTX
MSFT
NVDA
AAPL
GOOGL
AMZN
META
COST
AVGO
LLY
```

---

## 5.2 watchlist

Stores user-defined watchlists.

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5.3 watchlist_symbol

Maps symbols to watchlists.

```sql
CREATE TABLE IF NOT EXISTS watchlist_symbol (
    watchlist_id TEXT,
    symbol TEXT,
    priority INTEGER DEFAULT 0,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (watchlist_id, symbol)
);
```

---

## 5.4 daily_price

Stores historical OHLCV data.

```sql
CREATE TABLE IF NOT EXISTS daily_price (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    adjusted_close DOUBLE,
    volume BIGINT,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trade_date)
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_daily_price_symbol_date
ON daily_price(symbol, trade_date);
```

---

## 5.5 corporate_event

Stores earnings, FDA events, macro-sensitive events and other symbol-level events.

```sql
CREATE TABLE IF NOT EXISTS corporate_event (
    event_id TEXT PRIMARY KEY,
    symbol TEXT,
    event_date DATE NOT NULL,
    event_type TEXT,          -- EARNINGS, FDA, SPLIT, DIVIDEND, PRODUCT, OTHER
    title TEXT,
    description TEXT,
    source TEXT,
    importance INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5.6 macro_event

Stores macro calendar events.

```sql
CREATE TABLE IF NOT EXISTS macro_event (
    event_id TEXT PRIMARY KEY,
    event_date DATE NOT NULL,
    event_type TEXT,          -- CPI, PCE, FOMC, NFP, RATE_DECISION, OTHER
    title TEXT,
    description TEXT,
    importance INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5.7 news_item

Stores market and company news metadata and summaries.

```sql
CREATE TABLE IF NOT EXISTS news_item (
    news_id TEXT PRIMARY KEY,
    published_at TIMESTAMP,
    symbol TEXT,
    title TEXT,
    summary TEXT,
    source TEXT,
    url TEXT,
    sentiment_score DOUBLE,
    importance INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 6. Indicator Tables

---

## 6.1 daily_indicator

Stores calculated technical indicators.

```sql
CREATE TABLE IF NOT EXISTS daily_indicator (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,

    ma5 DOUBLE,
    ma10 DOUBLE,
    ma20 DOUBLE,
    ma30 DOUBLE,
    ma50 DOUBLE,
    ma100 DOUBLE,
    ma200 DOUBLE,

    ema20 DOUBLE,
    ema50 DOUBLE,

    atr14 DOUBLE,
    rsi14 DOUBLE,
    adx14 DOUBLE,

    volume_avg5 DOUBLE,
    volume_avg20 DOUBLE,
    volume_ratio_5 DOUBLE,
    volume_ratio_20 DOUBLE,

    return_1d DOUBLE,
    return_5d DOUBLE,
    return_20d DOUBLE,

    volatility_20d DOUBLE,
    volatility_60d DOUBLE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trade_date)
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_daily_indicator_symbol_date
ON daily_indicator(symbol, trade_date);
```

---

# 7. Signal Tables

---

## 7.1 daily_signal

Stores rule-based signals generated by analysis-engine.

```sql
CREATE TABLE IF NOT EXISTS daily_signal (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,

    market_regime TEXT,       -- TREND_UP, TREND_DOWN, RANGE, HIGH_RISK
    trend_state TEXT,         -- STRONG_UP, WEAK_UP, RANGE, WEAK_DOWN, STRONG_DOWN
    price_location TEXT,      -- ABOVE_MA200, BELOW_MA200, NEAR_MA200

    gap_type TEXT,            -- NONE, BREAKAWAY, EXHAUSTION, SHAKEOUT, PANIC
    gap_direction TEXT,       -- UP, DOWN, NONE
    gap_percent DOUBLE,

    false_breakdown_score DOUBLE,
    volume_confirmation_score DOUBLE,
    risk_score DOUBLE,

    action_hint TEXT,         -- HOLD, WATCH, ADD, REDUCE, EXIT, RE_ENTRY, AVOID
    confidence DOUBLE,

    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_daily_signal_symbol_date
ON daily_signal(symbol, trade_date);
```

---

## 7.2 signal_detail

Stores detailed signal components for explainability.

```sql
CREATE TABLE IF NOT EXISTS signal_detail (
    detail_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    component TEXT,           -- TREND, GAP, VOLUME, BREAKDOWN, RISK
    rule_name TEXT,
    rule_value TEXT,
    score DOUBLE,
    explanation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Example:

```text
component: BREAKDOWN
rule_name: close_back_above_ma200
score: 25
explanation: Price closed back above MA200 after intraday breakdown.
```

---

# 8. Portfolio Tables

---

## 8.1 portfolio_account

Stores high-level account metadata.

```sql
CREATE TABLE IF NOT EXISTS portfolio_account (
    account_id TEXT PRIMARY KEY,
    broker TEXT,              -- SCHWAB, VANGUARD, MANUAL
    account_name TEXT,
    account_type TEXT,        -- TAXABLE, IRA, ROTH, OTHER
    base_currency TEXT DEFAULT 'USD',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 8.2 portfolio_position_snapshot

Stores daily position snapshots.

```sql
CREATE TABLE IF NOT EXISTS portfolio_position_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    account_id TEXT,
    snapshot_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    quantity DOUBLE,
    market_price DOUBLE,
    market_value DOUBLE,
    cost_basis DOUBLE,
    unrealized_pnl DOUBLE,
    unrealized_pnl_percent DOUBLE,
    portfolio_weight DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_position_snapshot_date_symbol
ON portfolio_position_snapshot(snapshot_date, symbol);
```

---

## 8.3 portfolio_risk_snapshot

Stores daily portfolio-level risk metrics.

```sql
CREATE TABLE IF NOT EXISTS portfolio_risk_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    snapshot_date DATE NOT NULL,

    total_market_value DOUBLE,
    cash_value DOUBLE,
    equity_value DOUBLE,

    top1_weight DOUBLE,
    top5_weight DOUBLE,
    sector_concentration_score DOUBLE,

    portfolio_risk_score DOUBLE,
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 9. Trade Plan Tables

---

## 9.1 trade_plan

Stores system-generated trade plans.

```sql
CREATE TABLE IF NOT EXISTS trade_plan (
    plan_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    plan_date DATE NOT NULL,

    action TEXT NOT NULL,       -- HOLD, WATCH, ADD, REDUCE, EXIT, RE_ENTRY, AVOID
    strategy_type TEXT,         -- TREND, RANGE, FALSE_BREAKDOWN, GAP, FUNDAMENTAL, INDEX_DCA

    thesis TEXT,
    reason TEXT,

    entry_condition TEXT,
    entry_price DOUBLE,

    stop_type TEXT,             -- NONE, STOP, STOP_LIMIT, STRUCTURE_CONFIRMATION
    stop_price DOUBLE,
    stop_limit_price DOUBLE,

    target_price_1 DOUBLE,
    target_price_2 DOUBLE,

    position_size_percent DOUBLE,
    position_size_value DOUBLE,

    risk_reward_ratio DOUBLE,
    confidence DOUBLE,

    invalid_condition TEXT,

    status TEXT DEFAULT 'DRAFT', -- DRAFT, REVIEWED, APPROVED, REJECTED, EXPIRED, EXECUTED

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_trade_plan_date_symbol
ON trade_plan(plan_date, symbol);
```

---

## 9.2 trade_plan_signal_link

Links trade plans to underlying signals.

```sql
CREATE TABLE IF NOT EXISTS trade_plan_signal_link (
    plan_id TEXT,
    signal_id TEXT,
    PRIMARY KEY (plan_id, signal_id)
);
```

---

# 10. Order Draft Tables

---

## 10.1 order_draft

Stores broker-ready order drafts.

```sql
CREATE TABLE IF NOT EXISTS order_draft (
    draft_id TEXT PRIMARY KEY,
    plan_id TEXT,
    broker TEXT DEFAULT 'SCHWAB',
    account_id TEXT,

    symbol TEXT NOT NULL,
    instruction TEXT,           -- BUY, SELL
    order_type TEXT,            -- MARKET, LIMIT, STOP, STOP_LIMIT
    quantity DOUBLE,

    limit_price DOUBLE,
    stop_price DOUBLE,
    stop_limit_price DOUBLE,

    time_in_force TEXT DEFAULT 'DAY', -- DAY, GTC
    session TEXT DEFAULT 'NORMAL',

    status TEXT DEFAULT 'PENDING_REVIEW',
    -- PENDING_REVIEW, APPROVED, REJECTED, SUBMITTED, CANCELED, FAILED

    broker_order_id TEXT,
    raw_payload TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_order_draft_status_date
ON order_draft(status, created_at);
```

---

## 10.2 approval_record

Stores human approval decisions.

```sql
CREATE TABLE IF NOT EXISTS approval_record (
    approval_id TEXT PRIMARY KEY,
    draft_id TEXT,
    plan_id TEXT,

    decision TEXT,              -- APPROVED, REJECTED, MODIFIED
    decision_note TEXT,

    approved_quantity DOUBLE,
    approved_limit_price DOUBLE,
    approved_stop_price DOUBLE,

    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 11. Daily CIO Brief Tables

---

## 11.1 daily_cio_brief

Stores generated Daily CIO Briefs.

```sql
CREATE TABLE IF NOT EXISTS daily_cio_brief (
    brief_id TEXT PRIMARY KEY,
    brief_date DATE NOT NULL,

    market_summary TEXT,
    portfolio_summary TEXT,
    risk_summary TEXT,
    trade_plan_summary TEXT,
    order_draft_summary TEXT,
    final_recommendation TEXT,

    markdown_path TEXT,
    json_payload TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Recommended index:

```sql
CREATE INDEX IF NOT EXISTS idx_daily_cio_brief_date
ON daily_cio_brief(brief_date);
```

---

# 12. Investment Journal Tables

---

## 12.1 journal_entry

Stores daily and trade-level journal entries.

```sql
CREATE TABLE IF NOT EXISTS journal_entry (
    journal_id TEXT PRIMARY KEY,
    journal_date DATE NOT NULL,

    symbol TEXT,
    plan_id TEXT,
    draft_id TEXT,

    entry_type TEXT,            -- DAILY, TRADE, REVIEW, NOTE
    action TEXT,

    thesis TEXT,
    decision_reason TEXT,
    user_note TEXT,

    market_regime TEXT,
    confidence DOUBLE,

    outcome_5d DOUBLE,
    outcome_20d DOUBLE,
    outcome_60d DOUBLE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## 12.2 performance_review

Stores strategy-level performance summaries.

```sql
CREATE TABLE IF NOT EXISTS performance_review (
    review_id TEXT PRIMARY KEY,
    review_date DATE NOT NULL,

    strategy_type TEXT,
    period_start DATE,
    period_end DATE,

    trade_count INTEGER,
    win_rate DOUBLE,
    average_return DOUBLE,
    median_return DOUBLE,
    max_drawdown DOUBLE,
    best_trade_symbol TEXT,
    worst_trade_symbol TEXT,

    summary TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 13. Backtest Tables

---

## 13.1 backtest_run

Stores backtest metadata.

```sql
CREATE TABLE IF NOT EXISTS backtest_run (
    run_id TEXT PRIMARY KEY,
    run_name TEXT,
    strategy_type TEXT,

    start_date DATE,
    end_date DATE,

    universe TEXT,
    parameters TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 13.2 backtest_trade

Stores simulated trades.

```sql
CREATE TABLE IF NOT EXISTS backtest_trade (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT,

    symbol TEXT,
    entry_date DATE,
    exit_date DATE,

    entry_price DOUBLE,
    exit_price DOUBLE,

    quantity DOUBLE,
    pnl DOUBLE,
    return_percent DOUBLE,
    max_drawdown DOUBLE,

    exit_reason TEXT
);
```

---

## 13.3 backtest_metric

Stores backtest-level metrics.

```sql
CREATE TABLE IF NOT EXISTS backtest_metric (
    metric_id TEXT PRIMARY KEY,
    run_id TEXT,

    cagr DOUBLE,
    sharpe DOUBLE,
    max_drawdown DOUBLE,
    win_rate DOUBLE,
    average_trade_return DOUBLE,
    trade_count INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 14. Pydantic Model Mapping

The Python codebase should define matching Pydantic models in:

```text
shared/models/
├── market.py
├── indicators.py
├── signals.py
├── portfolio.py
├── trade_plan.py
├── order_draft.py
├── journal.py
└── brief.py
```

Example:

```python
from pydantic import BaseModel
from datetime import date
from typing import Optional


class TradePlan(BaseModel):
    plan_id: str
    symbol: str
    plan_date: date
    action: str
    strategy_type: Optional[str] = None
    thesis: Optional[str] = None
    entry_condition: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    position_size_percent: Optional[float] = None
    confidence: Optional[float] = None
    invalid_condition: Optional[str] = None
    status: str = "DRAFT"
```

---

# 15. Naming Conventions

## Table Names

Use singular or descriptive snake_case table names.

Examples:

```text
daily_price
daily_indicator
daily_signal
trade_plan
order_draft
journal_entry
```

## Primary Keys

Use explicit text IDs.

Examples:

```text
plan_id
draft_id
signal_id
journal_id
```

## Dates

Use:

```text
trade_date
plan_date
brief_date
journal_date
```

## Timestamps

Use:

```text
created_at
updated_at
```

---

# 16. ID Generation Rules

Use deterministic readable IDs where possible.

Examples:

```text
SIG-20260530-VRTX-001
TP-20260530-VRTX-001
OD-20260530-VRTX-001
BRIEF-20260530
JRN-20260530-VRTX-001
```

---

# 17. MVP Database Initialization

Create script:

```text
scripts/init_db.py
```

Purpose:

- Create DuckDB file
- Create all tables
- Create indexes
- Insert default watchlists
- Insert default symbols

Default watchlists:

```text
core_index
active_watchlist
long_term_compounders
medical_leaders
ai_leaders
```

Default symbols:

```text
SPY
QQQ
MSFT
AAPL
NVDA
GOOGL
AMZN
META
VRTX
COST
AVGO
LLY
```

---

# 18. Data Retention Policy

## Market Data

Keep indefinitely.

## Signals

Keep indefinitely.

## Trade Plans

Keep indefinitely.

## Order Drafts

Keep indefinitely.

## Journal

Keep indefinitely.

Rationale:

The system should support long-term behavioral review and strategy improvement.

---

# 19. Backup Strategy

MVP backup:

```text
data/db/personal_cio.duckdb
```

Backup frequency:

- Daily local backup
- Weekly cloud backup

Recommended path:

```text
backup/
├── daily/
└── weekly/
```

---

# 20. Future Database Evolution

## Phase 1

DuckDB only.

## Phase 2

DuckDB + SQLite.

- DuckDB for analytics
- SQLite for application state and broker workflow

## Phase 3

DuckDB + PostgreSQL.

- DuckDB for analytics and backtesting
- PostgreSQL for multi-user / web / broker workflow

---

# 21. Success Criteria

The database design is successful if it can support:

- Loading historical prices
- Calculating daily indicators
- Generating daily signals
- Creating trade plans
- Creating order drafts
- Recording user approvals
- Generating Daily CIO Brief
- Recording investment journal
- Running basic backtests
- Producing weekly/monthly reviews

The MVP database should enable the full closed loop:

```text
Market Data
    ↓
Indicators
    ↓
Signals
    ↓
Trade Plans
    ↓
Order Drafts
    ↓
Human Approval
    ↓
Journal
    ↓
Performance Review
```
