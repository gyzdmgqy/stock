-- 第 1 版：数据库设计文档中的 MVP 表和索引。

CREATE TABLE symbol (
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

CREATE TABLE watchlist (
    watchlist_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE watchlist_symbol (
    watchlist_id TEXT,
    symbol TEXT,
    priority INTEGER DEFAULT 0,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (watchlist_id, symbol)
);

CREATE TABLE daily_price (
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

CREATE INDEX idx_daily_price_symbol_date
ON daily_price(symbol, trade_date);

CREATE TABLE corporate_event (
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

CREATE TABLE macro_event (
    event_id TEXT PRIMARY KEY,
    event_date DATE NOT NULL,
    event_type TEXT,          -- CPI, PCE, FOMC, NFP, RATE_DECISION, OTHER
    title TEXT,
    description TEXT,
    importance INTEGER DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE news_item (
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

CREATE TABLE intraday_price (
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

CREATE TABLE daily_indicator (
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

CREATE INDEX idx_daily_indicator_symbol_date
ON daily_indicator(symbol, trade_date);

CREATE TABLE daily_signal (
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

CREATE INDEX idx_daily_signal_symbol_date
ON daily_signal(symbol, trade_date);

CREATE TABLE signal_detail (
    detail_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    component TEXT,           -- See SignalComponent enum
    rule_name TEXT,
    rule_value TEXT,
    score DOUBLE,
    explanation TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE portfolio_account (
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

CREATE TABLE portfolio_position_snapshot (
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

CREATE INDEX idx_position_snapshot_date_symbol
ON portfolio_position_snapshot(snapshot_date, symbol);

CREATE TABLE portfolio_risk_snapshot (
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

CREATE TABLE portfolio_cash_snapshot (
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

CREATE TABLE broker_transaction (
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

CREATE TABLE trade_plan (
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

    target_price_1 DECIMAL(20, 6),
    target_price_2 DECIMAL(20, 6),

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

CREATE INDEX idx_trade_plan_date_symbol
ON trade_plan(plan_date, symbol);

CREATE TABLE trade_plan_signal_link (
    plan_id TEXT,
    signal_id TEXT,
    PRIMARY KEY (plan_id, signal_id)
);

CREATE TABLE order_draft (
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

CREATE INDEX idx_order_draft_status_date
ON order_draft(status, created_at);

CREATE TABLE approval_record (
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

CREATE TABLE daily_cio_brief (
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

CREATE INDEX idx_daily_cio_brief_date
ON daily_cio_brief(brief_date);

CREATE TABLE journal_entry (
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

CREATE TABLE performance_review (
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

CREATE TABLE trade_outcome (
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

CREATE TABLE backtest_run (
    run_id TEXT PRIMARY KEY,
    run_name TEXT,
    strategy_type TEXT,

    start_date DATE,
    end_date DATE,

    universe TEXT,
    parameters TEXT,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backtest_trade (
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

CREATE TABLE backtest_metric (
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
