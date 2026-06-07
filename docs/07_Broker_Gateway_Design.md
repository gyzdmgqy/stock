# Personal CIO System
## Broker Gateway Design V1.0

---

# 1. Purpose

This document defines the design of the **Broker Gateway** module for the Personal CIO System.

The Broker Gateway is responsible for connecting Personal CIO System with brokerage accounts.

For MVP and early production, the primary supported broker is:

```text
Charles Schwab
```

Vanguard will initially be supported through CSV import rather than API integration.

The Broker Gateway must support the Human-in-the-Loop principle:

```text
System generates order drafts.
User reviews and approves.
Broker executes only after approval.
```

The Broker Gateway must never submit orders automatically without explicit user approval.

---

# 2. Scope

## 2.1 In Scope

The Broker Gateway supports:

- Broker account connection
- Account metadata synchronization
- Position synchronization
- Cash balance synchronization
- Transaction import
- Order draft generation
- User approval tracking
- Approved order submission
- Order status synchronization
- Error handling and audit logging

---

## 2.2 Out of Scope for MVP

The MVP does not support:

- Fully automated trading
- Options trading
- Margin trading
- Short selling
- Intraday high-frequency trading
- Multi-user account management
- Tax optimization
- Non-approved order submission
- Unsupported Vanguard API automation

---

# 3. Supported Brokers

## 3.1 Charles Schwab

Role:

```text
Primary active trading broker
```

Usage:

- Schwab Roth IRA
- Active individual stock trading
- Trade Planner execution account
- Limit order draft generation
- Stop limit order draft generation
- Position and transaction synchronization

System role:

```yaml
broker: SCHWAB
account_role: ACTIVE_TRADING
order_draft_enabled: true
api_sync_enabled: true
manual_csv_import_enabled: true
```

---

## 3.2 Vanguard

Role:

```text
Core passive broker
```

Usage:

- Vanguard Roth IRA
- Long-term VOO / QQQ holding
- Existing individual stocks are exit-only
- No new individual stock purchases

System role:

```yaml
broker: VANGUARD
account_role: CORE_PASSIVE
order_draft_enabled: false
api_sync_enabled: false
manual_csv_import_enabled: true
individual_stock_policy: EXIT_ONLY
```

Initial support:

```text
CSV import only
```

---

# 4. Design Principles

## 4.1 Safety First

The Broker Gateway must be conservative by default.

Default behavior:

```text
read-only
```

Order submission must be explicitly enabled.

---

## 4.2 Human Approval Required

All order submission flow must follow:

```text
Trade Plan
    ↓
Order Draft
    ↓
User Review
    ↓
User Approval
    ↓
Broker Submission
```

No direct path from Trade Planner to broker order execution is allowed.

---

## 4.3 Broker-Neutral Core

The Trade Planner generates broker-neutral order intent.

The Broker Gateway converts broker-neutral order intent into broker-specific payloads.

This allows future support for:

- Schwab
- IBKR
- Fidelity
- Vanguard CSV
- Manual broker records

---

## 4.4 Full Audit Trail

Every broker-related action must be logged:

- Account sync
- Position sync
- Transaction import
- Order draft creation
- Approval decision
- Order submission
- Broker response
- Error response

---

# 5. Broker Gateway Architecture

```text
broker-gateway-schwab/
├── src/
│   ├── auth/
│   ├── accounts/
│   ├── positions/
│   ├── transactions/
│   ├── orders/
│   ├── drafts/
│   ├── approvals/
│   ├── csv_import/
│   ├── adapters/
│   ├── validators/
│   ├── audit/
│   └── api/
├── config/
├── tests/
└── README.md
```

---

# 6. Core Components

## 6.1 Auth Manager

Responsible for broker authentication.

Responsibilities:

- Store OAuth metadata
- Refresh tokens
- Validate connection state
- Detect expired credentials
- Return structured auth errors

Important:

```text
Secrets must never be committed to Git.
```

Credentials should be stored in:

```text
.env
```

or local encrypted secret storage.

---

## 6.2 Account Sync Service

Responsible for account metadata.

Output:

```json
{
  "account_id": "SCHWAB_ROTH",
  "broker": "SCHWAB",
  "account_type": "ROTH_IRA",
  "account_role": "ACTIVE_TRADING",
  "base_currency": "USD",
  "is_active": true
}
```

---

## 6.3 Position Sync Service

Responsible for current position snapshots.

Output:

```json
{
  "snapshot_id": "POS-20260607-SCHWAB-VRTX",
  "account_id": "SCHWAB_ROTH",
  "broker": "SCHWAB",
  "symbol": "VRTX",
  "quantity": 10,
  "market_price": 462.1,
  "market_value": 4621.0,
  "cost_basis": 4500.0,
  "unrealized_pnl": 121.0,
  "portfolio_weight": 0.0102,
  "snapshot_date": "2026-06-07"
}
```

---

## 6.4 Transaction Import Service

Responsible for importing real executed transactions.

Supported sources:

```text
Schwab API
Schwab CSV
Vanguard CSV
Manual input
```

Output:

```json
{
  "transaction_id": "TXN-20260607-SCHWAB-VRTX-001",
  "broker": "SCHWAB",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "transaction_type": "BUY",
  "quantity": 10,
  "price": 461.75,
  "gross_amount": 4617.5,
  "fee": 0.0,
  "net_amount": 4617.5,
  "order_type": "LIMIT",
  "source": "API",
  "trade_date": "2026-06-07"
}
```

---

## 6.5 Order Draft Service

Responsible for converting Trade Plans into Order Drafts.

Input:

```json
{
  "plan_id": "TP-20260607-VRTX-001",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "instruction": "BUY",
  "order_type": "LIMIT",
  "quantity": 10,
  "limit_price": 462.0,
  "time_in_force": "DAY"
}
```

Output:

```json
{
  "draft_id": "OD-20260607-VRTX-001",
  "plan_id": "TP-20260607-VRTX-001",
  "broker": "SCHWAB",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "instruction": "BUY",
  "order_type": "LIMIT",
  "quantity": 10,
  "limit_price": 462.0,
  "status": "PENDING_REVIEW"
}
```

---

## 6.6 Approval Service

Responsible for storing user approval decisions.

Approval decisions:

```text
APPROVED
REJECTED
MODIFIED
DEFERRED
```

Output:

```json
{
  "approval_id": "APR-20260607-VRTX-001",
  "draft_id": "OD-20260607-VRTX-001",
  "plan_id": "TP-20260607-VRTX-001",
  "decision": "APPROVED",
  "decision_note": "Approved after manual review.",
  "approved_quantity": 10,
  "approved_limit_price": 462.0,
  "decided_at": "2026-06-07T22:05:00Z"
}
```

---

## 6.7 Order Submission Service

Responsible for submitting approved orders to Schwab.

Hard rule:

```text
Only APPROVED order drafts can be submitted.
```

The service must validate:

- Draft status is APPROVED
- Linked Trade Plan exists
- Account role allows action
- Cash or position is available
- Order payload is valid
- User approval exists
- No blocking risk rule remains active

---

## 6.8 Order Status Sync Service

Responsible for retrieving broker order status.

Status values:

```text
SUBMITTED
FILLED
PARTIALLY_FILLED
CANCELED
REJECTED
FAILED
UNKNOWN
```

The result should update:

- order_draft
- broker_transaction
- journal_entry

---

# 7. Broker-Neutral Order Intent

Trade Planner outputs broker-neutral order intent.

Example:

```json
{
  "plan_id": "TP-20260607-VRTX-001",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "instruction": "BUY",
  "order_type": "LIMIT",
  "quantity": 10,
  "limit_price": 462.0,
  "stop_price": null,
  "stop_limit_price": null,
  "time_in_force": "DAY"
}
```

The Broker Gateway converts this to Schwab-specific payload internally.

---

# 8. Supported Order Types

## 8.1 MVP Order Types

MVP should support:

```text
MARKET
LIMIT
STOP
STOP_LIMIT
```

However, the system should strongly prefer:

```text
LIMIT
STOP_LIMIT
```

for Personal CIO-generated orders.

---

## 8.2 Time in Force

Supported values:

```text
DAY
GTC
```

MVP default:

```text
DAY
```

---

## 8.3 Session

Supported values:

```text
NORMAL
EXTENDED
```

MVP default:

```text
NORMAL
```

---

# 9. Safety Rules

## 9.1 No Automatic Submission

Forbidden:

```text
Trade Plan → Broker Submit
```

Required:

```text
Trade Plan → Order Draft → User Approval → Broker Submit
```

---

## 9.2 Account Role Check

Before creating order draft:

```text
Check account_role.
Check trading_allowed.
Check individual_stock_policy.
```

Example:

```text
Vanguard CORE_PASSIVE:
  new individual stock BUY is blocked.

Schwab ACTIVE_TRADING:
  individual stock BUY is allowed.
```

---

## 9.3 Confidence Gate

Order draft should not be generated if:

```text
confidence < minimum_order_draft_confidence
```

Default:

```yaml
minimum_order_draft_confidence: 70
```

---

## 9.4 Cash / Position Check

Before submission:

For BUY:

```text
available_cash >= estimated_order_value
```

For SELL:

```text
available_quantity >= order_quantity
```

---

## 9.5 Duplicate Order Prevention

The system must detect duplicate drafts.

Duplicate definition:

```text
same account_id
same symbol
same instruction
same order_type
same limit_price
same trade_date
same plan_id
```

---

## 9.6 Event Risk Block

The Broker Gateway must respect risk blocks from Trade Planner.

Example:

```text
Do not submit new BUY orders if earnings are within blocked window,
unless user explicitly overrides.
```

---

# 10. Order Draft Lifecycle

```text
PENDING_REVIEW
    ↓
APPROVED / REJECTED / MODIFIED / DEFERRED
    ↓
SUBMITTED
    ↓
FILLED / PARTIALLY_FILLED / CANCELED / FAILED
```

---

# 11. Database Tables Used

The Broker Gateway reads/writes the following DuckDB tables:

```text
portfolio_account
portfolio_position_snapshot
broker_transaction
trade_plan
order_draft
approval_record
journal_entry
```

---

# 12. CSV Import Design

## 12.1 Why CSV Import

CSV import is required because:

- Vanguard API support is limited for this use case
- CSV import is safe
- CSV import is broker-neutral
- CSV import works for historical records
- CSV import allows manual correction

---

## 12.2 CSV Import Sources

MVP should support:

```text
Schwab positions CSV
Schwab transactions CSV
Vanguard positions CSV
Vanguard transactions CSV
Manual normalized CSV
```

---

## 12.3 CSV Import Workflow

```text
1. User downloads CSV from broker.
2. User places CSV under imports/raw/.
3. Importer detects broker format.
4. Importer normalizes fields.
5. User reviews imported records.
6. System writes normalized records to DuckDB.
7. Investment Journal uses imported records for performance review.
```

---

## 12.4 Import Folder Structure

```text
imports/
├── raw/
│   ├── schwab/
│   └── vanguard/
├── normalized/
└── archive/
```

---

# 13. Broker Transaction Normalization

All broker transactions should be normalized to:

```text
transaction_id
broker
account_id
symbol
transaction_time
trade_date
settlement_date
transaction_type
quantity
price
gross_amount
fee
net_amount
order_type
broker_order_id
source
source_file
note
```

---

# 14. Vanguard Exit-Only Handling

For Vanguard Roth IRA:

```text
New individual stock BUY orders are blocked.
Existing individual stock SELL plans may be generated.
After SELL, replacement plan should buy VOO / QQQ.
Future re-entry of the same individual stock must be routed to Schwab.
```

Example:

```yaml
account_id: VANGUARD_ROTH
account_role: CORE_PASSIVE
individual_stock_policy: EXIT_ONLY
replacement:
  VOO: 0.7
  QQQ: 0.3
future_reentry_account: SCHWAB_ROTH
```

---

# 15. Schwab Active Trading Handling

For Schwab Roth IRA:

```text
Individual stock trading is allowed.
Trade Planner is enabled.
Order drafts are enabled.
Approved order submission may be enabled in later phase.
```

Example:

```yaml
account_id: SCHWAB_ROTH
account_role: ACTIVE_TRADING
individual_stock_policy: ACTIVE_ALLOWED
order_draft_enabled: true
```

---

# 16. Error Handling

All errors must be structured.

Example:

```json
{
  "message_id": "ERR-20260607-SCHWAB-001",
  "message_type": "ERROR",
  "source": "broker-gateway-schwab",
  "created_at": "2026-06-07T22:10:00Z",
  "payload": {
    "error_type": "AUTH_ERROR",
    "error_message": "Schwab token expired.",
    "retryable": true,
    "suggested_action": "Refresh OAuth token."
  }
}
```

Error types:

```text
AUTH_ERROR
BROKER_API_ERROR
DATA_MISSING
CSV_PARSE_ERROR
VALIDATION_ERROR
DUPLICATE_ORDER
INSUFFICIENT_CASH
INSUFFICIENT_POSITION
RISK_RULE_BLOCKED
USER_APPROVAL_REQUIRED
UNKNOWN
```

---

# 17. Audit Logging

Audit log must record:

- Auth events
- Account sync events
- Position sync events
- Transaction import events
- Order draft creation
- Approval decisions
- Order submission attempts
- Broker responses
- Errors

Audit log output:

```text
logs/broker.log
```

Database audit record may also be added in future versions.

---

# 18. Configuration

Recommended config file:

```text
config/broker.yaml
```

Example:

```yaml
brokers:
  schwab:
    enabled: true
    mode: read_only
    order_submission_enabled: false
    order_draft_enabled: true

  vanguard:
    enabled: true
    mode: csv_only
    order_submission_enabled: false
    order_draft_enabled: false

accounts:
  SCHWAB_ROTH:
    broker: SCHWAB
    account_type: ROTH_IRA
    account_role: ACTIVE_TRADING
    order_draft_enabled: true

  VANGUARD_ROTH:
    broker: VANGUARD
    account_type: ROTH_IRA
    account_role: CORE_PASSIVE
    individual_stock_policy: EXIT_ONLY
    default_replacement:
      VOO: 0.7
      QQQ: 0.3
```

---

# 19. Pydantic Model Draft

```python
from datetime import date, datetime
from typing import Optional, Dict
from pydantic import BaseModel


class OrderDraft(BaseModel):
    draft_id: str
    plan_id: str
    broker: str
    account_id: str
    symbol: str
    instruction: str
    order_type: str
    quantity: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    stop_limit_price: Optional[float] = None
    time_in_force: str = "DAY"
    session: str = "NORMAL"
    status: str = "PENDING_REVIEW"
    raw_payload: Optional[Dict] = None


class ApprovalDecision(BaseModel):
    approval_id: str
    draft_id: str
    plan_id: str
    decision: str
    decision_note: Optional[str] = None
    approved_quantity: Optional[float] = None
    approved_limit_price: Optional[float] = None
    approved_stop_price: Optional[float] = None
    decided_at: datetime


class BrokerTransaction(BaseModel):
    transaction_id: str
    broker: str
    account_id: str
    symbol: Optional[str] = None
    transaction_time: Optional[datetime] = None
    trade_date: Optional[date] = None
    settlement_date: Optional[date] = None
    transaction_type: str
    quantity: Optional[float] = None
    price: Optional[float] = None
    gross_amount: Optional[float] = None
    fee: Optional[float] = None
    net_amount: Optional[float] = None
    order_type: Optional[str] = None
    broker_order_id: Optional[str] = None
    source: str
    source_file: Optional[str] = None
    note: Optional[str] = None
```

---

# 20. Development Phases

## Phase 1: CSV Import

- Import Schwab transactions CSV
- Import Vanguard transactions CSV
- Import positions CSV
- Normalize to broker_transaction
- Write to DuckDB

## Phase 2: Schwab Read-Only API

- Connect Schwab API
- Read accounts
- Read positions
- Read balances
- Read order status
- Read transactions if supported

## Phase 3: Order Draft Generation

- Convert Trade Plan to broker-neutral order draft
- Validate order draft
- Store as PENDING_REVIEW

## Phase 4: Human Approval

- User approves / rejects / modifies
- Store approval record
- Update order draft status

## Phase 5: Approved Order Submission

- Submit only approved orders
- Store broker response
- Sync order status
- Record execution in journal

---

# 21. Testing Strategy

## Unit Tests

Test:

- Order draft validation
- Account role rule enforcement
- Cash check
- Position check
- Duplicate order detection
- Vanguard exit-only enforcement

## Integration Tests

Test:

- CSV import to DuckDB
- Trade Plan to Order Draft
- Approval to Submission-ready status
- Order status sync mock

## Safety Tests

Must verify:

- No order can be submitted without approval
- Vanguard individual stock BUY is blocked
- Confidence below threshold blocks order draft
- Duplicate order draft is blocked
- Insufficient cash blocks buy submission
- Insufficient position blocks sell submission

---

# 22. Success Criteria

Broker Gateway is successful if:

- Schwab account and positions can be synchronized.
- Vanguard and Schwab CSV transactions can be imported.
- Real holdings and buy/sell history can be recorded.
- Trade Plans can be converted into order drafts.
- No order can be submitted without user approval.
- Vanguard is enforced as CORE_PASSIVE / EXIT_ONLY.
- Schwab is enforced as ACTIVE_TRADING.
- Every order draft can be traced to a Trade Plan.
- Every submitted order can be traced to approval.
- Every broker transaction can be used by Investment Journal for performance review.

The Broker Gateway must remain safe, auditable, and conservative.
