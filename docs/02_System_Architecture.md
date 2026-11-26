# Personal CIO System
## System Architecture Design V1.0

---

# 1. Architecture Overview

## System Mission

Personal CIO System is a Human-in-the-Loop investment decision platform.

The system is designed to:

- Collect market information
- Analyze signals
- Generate trade plans
- Generate order drafts
- Assist decision making
- Record and review investment decisions

The system is NOT designed to:

- Automatically trade
- Predict future prices
- Replace human judgment

---

# 2. High-Level Architecture

```text
market-data-service
        ↓
analysis-engine
        ↓
trade-planner
        ↓
broker-gateway (order drafts)
        ↓
personal-cio-agent (CIO brief)
        ↓
investment-journal
```

---

# 3. Core Design Principles

## Rule First, Agent Second

Rules generate signals.
Agents explain decisions.

## Human Approval Required

System Generates → User Reviews → User Approves → Broker Executes

No automatic order execution.

## Full Audit Trail

Everything must be recorded:

- Signals
- Plans
- Decisions
- Orders
- Results

## Loose Coupling

Every module must be independently replaceable.

---

# 4. Repository Architecture

One Python monorepo with these modules:

1. market-data-service
2. analysis-engine
3. trade-planner
4. broker-gateway
5. personal-cio-agent
6. investment-journal

---

# 5. Data Flow

## Daily Workflow

1. Download market data
2. Calculate indicators
3. Generate signals
4. Generate trade plans
5. Generate eligible order drafts through broker-gateway
6. Generate CIO Brief, including those drafts and prior journal reminders
7. Record the completed daily workflow in investment-journal

Persist each stage as it succeeds. The final journal stage does not delay storing
signals, plans, or drafts. Before analysis/planning, load the latest imported
positions, cash, and account policies; broker CSV import is a separate input step.
Review decisions and later executions create additional journal entries.

## User Workflow

1. Read CIO Brief
2. Review Trade Plans
3. Review Order Drafts
4. Approve / Modify / Reject
5. Submit to Broker

---

# 6. Database Architecture

MVP: DuckDB only. [Doc 04](04_Database_Design.md) is the single canonical schema.
Any later SQLite/PostgreSQL split is an optional future decision.

Core tables:

- symbol
- daily_price
- daily_signal
- trade_plan
- order_draft
- journal_entry

---

# 7. Analysis Engine

Indicator Layer:

- MA
- ATR
- RSI
- ADX
- VWAP

Signal Layer:

- Trend Signal
- Gap Signal
- False Breakdown Signal
- Volume Confirmation Signal

---

# 8. Trade Planner

Purpose:

Generate executable trade plans.

Output:

- Action
- Entry Price
- Stop Price
- Position Size
- Confidence
- Invalid Conditions

---

# 9. Personal CIO Agent

Purpose:

Generate Daily CIO Brief.

Daily Sections:

- Market
- Portfolio
- Opportunities
- Risks
- Trade Plans
- Order Drafts
- Summary

---

# 10. Broker Gateway

The neutral broker-gateway owns account, position, cash, and transaction imports,
order drafts, approvals, and broker adapters.

Build sequence follows [doc 10](10_TDD_Development_Plan_and_Codex_Prompts.md):

- Phase 8: Schwab and Vanguard CSV import.
- Phase 9: Local order drafts and approval services.
- Phases 10-11: Stable daily pipeline and local dashboard.
- Phase 12: Schwab read-only API.
- Phase 13: User-approved Schwab submission.

Vanguard remains CSV/manual execution only.

---

# 11. Investment Journal

Stores:

- Signals
- Plans
- Decisions
- Orders
- Results

Analytics:

- Win Rate
- Avg Return
- Drawdown
- Best Strategies
- Worst Strategies

---

# 12. Deployment Architecture

Start with local Python, DuckDB, Markdown/JSON reports, CSV imports, and a local
Streamlit dashboard. Home-server/cloud hosting is optional future work and is not
a prerequisite for Schwab integration. Doc 10 owns all numbered build phases.

Application timezone: America/Chicago, independent of host location. UTC storage
and exchange-session dates follow doc 04.

---

# 13. Security Design

API Keys:

Stored in .env

Broker Access:

Read-only by default.

Order Submission:

Always requires approval.

---

# 14. Architecture Success Criteria

Daily management time reduced from:

60–120 minutes

to

5–15 minutes.

Daily outputs:

- One CIO Brief
- One Trade Plan Set
- One Order Draft Set

The system should answer:

- What is happening?
- What should I do?
- Why?
- What are the risks?
