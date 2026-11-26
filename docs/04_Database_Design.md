# Personal CIO System
## Database Design V1.1

---

# 1. Purpose

This document is the single canonical database schema for Personal CIO System.
All CREATE TABLE definitions and persisted enum values are owned here. Other
documents describe behavior or message examples and must reference this schema.
The build order is owned by [doc 10](10_TDD_Development_Plan_and_Codex_Prompts.md).

Confirmed: DuckDB-only MVP and the richer journal fields originally in doc 08.
The relational-core-plus-JSON mapping below is the recommended design baseline,
pending the user's storage-design review. It is a concrete proposal, not a
previously approved storage decision. See [design decisions](11_Design_Alignment_and_Open_Decisions.md).

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

## 2.3 Storage Mapping Recommendation

Keep typed relational columns for identity, links, account, dates, status, action,
prices, quantity, confidence, and other frequently queried or validated values.
Use JSON for variable-length conditions, replacement allocations, structured
brief sections, and broker-specific payloads. Keep the nested Pydantic message
model; a repository mapper translates it to and from the relational row.

Each value has one authoritative storage location. Do not keep a second writable
copy of the complete TradePlan alongside its columns. Broker raw_payload is
derived from validated order columns and cannot override them. Preserve the
exact reviewed order in approval_record.approved_payload for audit comparison.

| Message path | Canonical storage |
|---|---|
| entry_order.type / entry_order.price | trade_plan.entry_order_type / entry_price |
| stop_order.type / stop_price / limit_price / condition / reason | stop_type / stop_price / stop_limit_price / stop_condition / stop_reason |
| position_size.percent_of_portfolio / estimated_value / quantity | position_size_percent / position_size_value / quantity |
| entry_condition / invalid_condition / exit_trigger | JSON arrays in the corresponding columns |
| replacement | JSON object mapping symbol to allocation fraction |
| DailyCioBrief structured summaries | Corresponding JSON summary columns |
| OrderDraft.raw_payload | Derived broker payload JSON |
| ApprovalDecision approved order | Immutable approved_payload JSON |

Use JSON arrays even for one condition. Empty arrays mean no conditions; NULL
means unavailable only where explicitly allowed. Parse and validate JSON through
shared models on every write and reconstruct the same model on read. Actionable
plans require nonempty invalid_condition; conditional exits also require
exit_trigger. Human explanations must not become executable conditions.

The current messages use percentage points for percent_of_portfolio (1.5 means
1.5%) and fractions for portfolio_weight and allocation ratios (0.015 means 1.5%).
Conversions must be explicit. Position sizing uses the individual account's
current equity (holdings plus cash); record sizing_basis=ACCOUNT and the actual
sizing_base_value with each sized plan. Run separate combined-portfolio exposure
checks across accounts; combined portfolio value never increases an account's
order-sizing budget. Account-based size limits and combined exposure limits must
both pass for new entries. Protective exits use action-specific risk checks.

## 2.4 Future Evolution

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

## 2.5 Time and Persistence Rules

Application/report/scheduler timezone is always America/Chicago, regardless of
the host timezone or travel. Store instants as UTC TIMESTAMPTZ; trade_date is the
exchange session date, not the host's calendar date. Use an exchange trading
calendar for trading-day horizons and event windows.

All writes for one business operation must be atomic. Use one coordinated local
writer; dashboard approvals, CSV imports, and scheduled runs must share that
writer or take an application lock and close connections between operations.
Initialization is idempotent; schema changes require versioned migrations.
Do not treat CREATE TABLE IF NOT EXISTS as a migration mechanism.

Validate enums from section 15 in shared/enums and at repository boundaries.
Validate referenced IDs and account consistency before committing linked records.
Round-trip tests must cover nested fields and the complete richer journal.
A rerun must preserve reviewed plans, approvals, and journal notes; changed inputs
produce a new plan ID and explicit supersedes_plan_id.

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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);
```

Example symbols:

```text
SPY
QQQ
VOO
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5.7 news_item

Stores market and company news metadata and summaries.

```sql
CREATE TABLE IF NOT EXISTS news_item (
    news_id TEXT PRIMARY KEY,
    published_at TIMESTAMPTZ,
    symbol TEXT,
    title TEXT,
    summary TEXT,
    source TEXT,
    url TEXT,
    sentiment_score DOUBLE,
    importance INTEGER DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5.8 intraday_price

Hourly storage is provisioned in Phase 2; ingestion remains optional for MVP.

```sql
CREATE TABLE IF NOT EXISTS intraday_price (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL DEFAULT '1h',
    bar_start TIMESTAMPTZ NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval, bar_start)
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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
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

    action_hint TEXT,         -- See Action enum (includes EXIT_ONLY)
    confidence DOUBLE,

    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    component TEXT,           -- See SignalComponent enum
    rule_name TEXT,
    rule_value TEXT,
    score DOUBLE,
    explanation TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    account_type TEXT,        -- TAXABLE, TRADITIONAL_IRA, ROTH_IRA, OTHER
    account_role TEXT NOT NULL, -- See canonical AccountRole enum
    individual_stock_policy TEXT,
    order_draft_enabled BOOLEAN DEFAULT FALSE,
    api_sync_enabled BOOLEAN DEFAULT FALSE,
    csv_import_enabled BOOLEAN DEFAULT TRUE,
    default_replacement JSON,
    base_currency TEXT DEFAULT 'USD',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    observed_at TIMESTAMPTZ,
    source TEXT,
    symbol TEXT NOT NULL,
    quantity DOUBLE,
    market_price DOUBLE,
    market_value DOUBLE,
    cost_basis DOUBLE,
    unrealized_pnl DOUBLE,
    unrealized_pnl_percent DOUBLE,
    portfolio_weight DOUBLE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    account_id TEXT, -- NULL denotes the combined portfolio

    total_market_value DOUBLE,
    cash_value DOUBLE,
    equity_value DOUBLE,

    top1_weight DOUBLE,
    top5_weight DOUBLE,
    sector_concentration_score DOUBLE,

    portfolio_risk_score DOUBLE,
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

---

## 8.4 portfolio_cash_snapshot

Cash availability is separate from positions; missing cash is unknown, never zero.

```sql
CREATE TABLE IF NOT EXISTS portfolio_cash_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    currency TEXT DEFAULT 'USD',
    cash_balance DECIMAL(20, 6),
    available_to_trade DECIMAL(20, 6),
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

## 8.5 broker_transaction

Shared normalized transactions from Schwab, Vanguard CSV, or manual input.
Source identifiers and deduplication keys are scoped to account and broker.
CSV/API reconciliation must preserve separate real fills that happen to have
identical prices and quantities. Sign conventions and matching rules must be
specified with broker sample formats before Phase 8.

```sql
CREATE TABLE IF NOT EXISTS broker_transaction (
    transaction_id TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    account_id TEXT NOT NULL,
    symbol TEXT,
    transaction_time TIMESTAMPTZ,
    trade_date DATE,
    settlement_date DATE,
    transaction_type TEXT NOT NULL,
    quantity DECIMAL(20, 8),
    price DECIMAL(20, 6),
    gross_amount DECIMAL(20, 6),
    fee DECIMAL(20, 6),
    net_amount DECIMAL(20, 6),
    order_type TEXT,
    broker_order_id TEXT,
    broker_transaction_id TEXT,
    plan_id TEXT,
    draft_id TEXT,
    source TEXT NOT NULL,
    source_file TEXT,
    deduplication_key TEXT NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (broker, account_id, deduplication_key)
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
    account_id TEXT NOT NULL,
    account_role TEXT NOT NULL, -- Role when the plan was generated
    supersedes_plan_id TEXT,
    primary_timeframe TEXT DEFAULT 'daily',
    execution_timeframe TEXT,
    rule_version TEXT,
    input_references JSON, -- Source table names, row IDs, and observed timestamps

    action TEXT NOT NULL,       -- See Action enum (includes EXIT_ONLY)
    strategy_type TEXT,         -- See StrategyType enum

    thesis TEXT,
    reason TEXT,

    entry_condition JSON,
    entry_order_type TEXT,
    entry_price DECIMAL(20, 6),

    stop_type TEXT,             -- See StopType enum; distinct from broker OrderType
    stop_price DECIMAL(20, 6),
    stop_limit_price DECIMAL(20, 6),
    stop_condition TEXT,
    stop_reason TEXT,

    target_price_1 DOUBLE,
    target_price_2 DOUBLE,

    position_size_percent DOUBLE,
    position_size_value DECIMAL(20, 6),
    quantity DECIMAL(20, 8),
    sizing_basis TEXT DEFAULT 'ACCOUNT', -- MVP sizing denominator: individual account equity
    sizing_base_value DECIMAL(20, 6),

    risk_reward_ratio DOUBLE,
    confidence DOUBLE,

    invalid_condition JSON,
    exit_trigger JSON,
    replacement JSON,
    future_reentry_account TEXT,

    status TEXT DEFAULT 'DRAFT', -- DRAFT, REVIEWED, APPROVED, REJECTED, EXPIRED, EXECUTED

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
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
    replaces_draft_id TEXT,
    broker TEXT NOT NULL,
    account_id TEXT,

    symbol TEXT NOT NULL,
    instruction TEXT,           -- BUY, SELL
    order_type TEXT,            -- MARKET, LIMIT, STOP, STOP_LIMIT
    quantity DECIMAL(20, 8),

    limit_price DECIMAL(20, 6),
    stop_price DECIMAL(20, 6),
    stop_limit_price DECIMAL(20, 6),

    time_in_force TEXT DEFAULT 'DAY', -- DAY, GTC
    session TEXT DEFAULT 'NORMAL',

    status TEXT DEFAULT 'PENDING_REVIEW',
    -- See OrderDraftStatus enum and transitions in section 15

    broker_order_id TEXT,
    raw_payload JSON,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
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

    decision TEXT,              -- APPROVED, REJECTED, MODIFIED, DEFERRED
    decision_note TEXT,

    approved_quantity DECIMAL(20, 8),
    approved_limit_price DECIMAL(20, 6),
    approved_stop_price DECIMAL(20, 6),
    approved_stop_limit_price DECIMAL(20, 6),
    approved_payload JSON, -- Exact reviewed order including account, side, session and TIF

    decided_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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

    market_summary JSON,
    portfolio_summary JSON,
    risk_summary JSON,
    trade_plan_summary JSON,
    order_draft_summary JSON,
    final_recommendation TEXT,

    markdown_path TEXT,
    journal_reminders JSON,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);
```

---

## 12.2 performance_review

Stores strategy-level performance summaries.

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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

---

## 12.3 trade_outcome

Canonical schema adopted from doc 08. Plan outcomes and actual execution outcomes
are distinct observations; do not combine their counts or returns. Reference-price
and partial-fill accounting policies remain to be agreed before Phase 6 outcomes.

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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);
```

The outcome_* fields in journal_entry are derived display summaries. trade_outcome
owns the calculation; update summaries atomically and test equality. Outcome
returns, benchmarks, and decision-quality metrics must have documented units and
reference-price rules before their implementation.

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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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

Models use the canonical enums in section 15. TradePlan keeps the nested API
shape illustrated in doc 06; persistence mapping is defined in section 2.3.
Exit plans use the same TradePlan model with exit_trigger, replacement, and
future_reentry_account. Order prices and quantities use Decimal in Python and
DECIMAL in SQL; indicator calculations may use floating point.
DailyCioBrief exports are assembled from stored summary sections; there is no
second writable json_payload copy.

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


## Canonical Enums and Status Transitions

These values consolidate the existing documents. Implementation uses shared/enums
and repository validation; SQL comments alone do not enforce enums.
SUBMITTING, EXPIRED, and UNKNOWN in the order lifecycle are recommended additions
to cover expiry and ambiguous submission outcomes. The transition policy below
is part of the proposed alignment baseline.

| Enum | Values |
|---|---|
| Broker | SCHWAB, VANGUARD, MANUAL |
| AccountType | TAXABLE, TRADITIONAL_IRA, ROTH_IRA, OTHER |
| AccountRole | CORE_PASSIVE, ACTIVE_TRADING, RETIREMENT_INDEX, CASH_RESERVE, MANUAL |
| IndividualStockPolicy | EXIT_ONLY, ACTIVE_ALLOWED |
| Action | HOLD, WATCH, ADD, REDUCE, EXIT, RE_ENTRY, AVOID, EXIT_ONLY |
| StrategyType | INDEX_DCA, TREND_FOLLOWING, RANGE_TRADING, FALSE_BREAKDOWN_REENTRY, GAP_CONTINUATION, GAP_EXHAUSTION_AVOID, VANGUARD_EXIT_ONLY, ACCOUNT_MIGRATION, RISK_REDUCTION, EARNINGS_RISK_CONTROL |
| StopType | NONE, PRICE_STOP, STOP_LIMIT, STRUCTURE_CONFIRMATION, TIME_STOP |
| OrderType | MARKET, LIMIT, STOP, STOP_LIMIT |
| OrderInstruction | BUY, SELL |
| TimeInForce | DAY, GTC |
| Session | NORMAL, EXTENDED |
| TradePlanStatus | DRAFT, REVIEWED, APPROVED, REJECTED, EXPIRED, EXECUTED |
| OrderDraftStatus | PENDING_REVIEW, APPROVED, REJECTED, MODIFIED, DEFERRED, EXPIRED, SUBMITTING, SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELED, FAILED, UNKNOWN |
| ApprovalDecision | APPROVED, REJECTED, MODIFIED, DEFERRED |
| JournalEntryType | DAILY, SIGNAL_REVIEW, TRADE_PLAN_REVIEW, ORDER_REVIEW, TRADE_EXECUTION, MANUAL_NOTE, WEEKLY_REVIEW, MONTHLY_REVIEW, PERFORMANCE_REVIEW, BEHAVIOR_REVIEW, ACCOUNT_MIGRATION |
| TransactionType | BUY, SELL, DIVIDEND, TRANSFER, FEE, INTEREST, CASH_SWEEP, OTHER |
| TransactionSource | API, CSV, MANUAL |
| MarketRegime | TREND_UP, TREND_DOWN, RANGE, HIGH_RISK |
| TrendState | STRONG_UP, WEAK_UP, RANGE, WEAK_DOWN, STRONG_DOWN |
| PriceLocation | ABOVE_MA200, BELOW_MA200, NEAR_MA200 |
| GapType | NONE, BREAKAWAY, EXHAUSTION, SHAKEOUT, PANIC |
| GapDirection | UP, DOWN, NONE |
| SignalComponent | TREND, GAP, VOLUME, BREAKDOWN, RISK, FUNDAMENTAL, PORTFOLIO, EXECUTION |
| ReviewType | WEEKLY, MONTHLY, QUARTERLY, STRATEGY, ACCOUNT, BEHAVIOR |
| EmotionTag | CALM, FEARFUL, FOMO, FRUSTRATED, CONFIDENT |
| OutcomeLabel | WIN, LOSS, FLAT, MISSED_OPPORTUNITY, AVOIDED_LOSS |
| ErrorType | DATA_MISSING, DATA_STALE, AUTH_ERROR, BROKER_API_ERROR, CSV_PARSE_ERROR, VALIDATION_ERROR, DUPLICATE_ORDER, INSUFFICIENT_CASH, INSUFFICIENT_POSITION, RISK_RULE_BLOCKED, USER_APPROVAL_REQUIRED, UNKNOWN |

DailySignal.action_hint uses Action, with account restrictions applied only by
the planner. IntradaySignal.action_hint is a separate execution vocabulary:
WAIT_FOR_LIMIT_ENTRY is the currently illustrated value. The remaining hourly
vocabulary is deferred until hourly behavior is specified; do not add execution
hints to Action. Optional hourly indicators/signals may be carried as messages;
persistent tables for them are outside the current MVP schema. A plan requiring
hourly confirmation must remain WATCH until the required hourly conditions are
confirmed with valid data. Missing, stale, or unconfirmed hourly evidence cannot
be replaced by a daily-only fallback or a conditional order draft.

MessageType values: MARKET_DATA_SNAPSHOT, INTRADAY_PRICE_SNAPSHOT, DAILY_INDICATOR,
HOURLY_INDICATOR, DAILY_SIGNAL, INTRADAY_SIGNAL, PORTFOLIO_SNAPSHOT,
BROKER_TRANSACTION, RISK_SNAPSHOT, TRADE_PLAN, ORDER_DRAFT, APPROVAL_DECISION,
DAILY_CIO_BRIEF, JOURNAL_ENTRY, PERFORMANCE_REVIEW, ERROR.
Exit/re-entry plans are TRADE_PLAN payloads, not separate message types.

| Old wording | Canonical interpretation |
|---|---|
| TREND / RANGE / FALSE_BREAKDOWN strategy | TREND_FOLLOWING / RANGE_TRADING / FALSE_BREAKDOWN_REENTRY |
| GAP strategy | Choose GAP_CONTINUATION or GAP_EXHAUSTION_AVOID explicitly |
| FUNDAMENTAL strategy | No automatic mapping; select an agreed strategy before implementation |
| STOP in plan stop_type | PRICE_STOP; STOP remains a broker OrderType |
| ROTH / IRA account type | ROTH_IRA / TRADITIONAL_IRA |
| NOTE journal entry | MANUAL_NOTE |
| TRADE / REVIEW journal entry | Select the specific execution/review entry type; do not guess |
| EXIT_ONLY | Account restriction or migration plan action, never a broker instruction |

PRICE_STOP can produce a STOP broker intent after review. STRUCTURE_CONFIRMATION
and TIME_STOP are monitored planning rules; they cannot be sent as broker order
types. A triggered rule generates a new reviewable SELL intent. VANGUARD_EXIT_ONLY
is a legacy-stock monitoring strategy; ACCOUNT_MIGRATION additionally tracks
replacement allocation. EXIT_ONLY alone does not mean "sell immediately."

Trade plan transitions:

- DRAFT -> REVIEWED.
- REVIEWED -> APPROVED or REJECTED.
- DRAFT, REVIEWED, or APPROVED -> EXPIRED when invalid or superseded, after any active broker orders are reconciled.
- APPROVED -> EXECUTED only after confirmed completion of its intended execution.
- REJECTED, EXPIRED, and EXECUTED do not transition to another state.
- Approving a plan does not authorize a broker order; draft approval is separate.

Order draft transitions:

| Current state | Allowed next states / meaning |
|---|---|
| PENDING_REVIEW | APPROVED, REJECTED, DEFERRED, MODIFIED, EXPIRED |
| DEFERRED | PENDING_REVIEW, REJECTED, MODIFIED, EXPIRED |
| APPROVED | SUBMITTING after revalidation; MODIFIED or EXPIRED before submission |
| SUBMITTING | SUBMITTED, REJECTED (broker rejection), FAILED (confirmed not accepted), UNKNOWN |
| UNKNOWN | Reconcile to SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, or FAILED from broker evidence |
| SUBMITTED | PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, UNKNOWN |
| PARTIALLY_FILLED | PARTIALLY_FILLED for additional fills, FILLED, CANCELED, UNKNOWN |
| REJECTED, MODIFIED, EXPIRED, FILLED, CANCELED, FAILED | Terminal for that draft ID |

A MODIFIED decision retires the old draft and creates a new PENDING_REVIEW draft
with replaces_draft_id. The new draft requires fresh approval. Approved fields
are immutable; approved_payload binds approval to account, symbol, instruction,
type, quantity, all prices, session, and time-in-force. The approved_* scalar
fields are projections of that same snapshot and must match it.

A timeout is UNKNOWN, not evidence of failure. Do not blindly resubmit UNKNOWN
orders. Reconcile broker acceptance and fills first. Approval decisions are
append-only; use the latest applicable decision for that exact immutable draft.
Track partial fills as distinct broker transactions. A canceled remainder does
not erase earlier fills, and a partially filled plan is not yet EXECUTED.

Journal outcome milestones describe which metrics are available; they are not a
journal status enum or an approval state machine.

---

# 16. ID Generation Rules

Use deterministic readable IDs where possible. Include account and strategy for
plans and drafts; use a stable input identity for reruns and a new ID for changed
intent. Never overwrite an approved intent to make a rerun idempotent.

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
- Insert VANGUARD_ROTH (CORE_PASSIVE) and SCHWAB_ROTH (ACTIVE_TRADING)
- Load account policies from config/accounts.yaml

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
VOO
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

## MVP Storage

DuckDB only.

## Optional Application-State Split

DuckDB + SQLite.

- DuckDB for analytics
- SQLite for application state and broker workflow

## Optional Server Storage

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
