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
personal-cio-agent
        ↓
broker-gateway-schwab
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

Repositories:

1. market-data-service
2. analysis-engine
3. trade-planner
4. personal-cio-agent
5. broker-gateway-schwab
6. investment-journal

---

# 5. Data Flow

## Daily Workflow

1. Download market data
2. Calculate indicators
3. Generate signals
4. Generate trade plans
5. Generate CIO Brief
6. Generate order drafts
7. Persist everything

## User Workflow

1. Read CIO Brief
2. Review Trade Plans
3. Review Order Drafts
4. Approve / Modify / Reject
5. Submit to Broker

---

# 6. Database Architecture

Phase 1:

- DuckDB
- SQLite

Phase 2:

- PostgreSQL

Core tables:

- symbol
- daily_price
- signal
- trade_plan
- order_draft
- journal

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

Phase 1:

Read-only account access.

Phase 2:

Order draft generation.

Phase 3:

User-approved submission.

Supported broker:

- Charles Schwab

Future:

- IBKR
- Fidelity
- Vanguard

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

Phase 1:

- Local Machine
- Python
- DuckDB
- Markdown Reports

Phase 2:

- Home Server
- Cloud VM

Phase 3:

- Streamlit Dashboard

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
