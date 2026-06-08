# Personal CIO System
## Deployment Guide V1.0

---

# 1. Purpose

This document defines how to deploy and run the Personal CIO System.

The deployment strategy follows the MVP principle:

```text
Simple first.
Local first.
Safe first.
Broker read-only first.
Human approval always required.
```

The system should initially run on a local machine as a single-user application. Future deployment can move to a home server, cloud VM, or Streamlit web dashboard after the core workflow is stable.

---

# 2. Deployment Goals

The deployment must support:

- Local development
- Local daily execution
- DuckDB-based storage
- Markdown / JSON report generation
- CSV import from Vanguard and Schwab
- Optional Schwab read-only API integration
- Future order draft approval workflow
- Safe handling of broker credentials
- Easy backup and recovery

---

# 3. Deployment Phases

## Phase 1: Local MVP

```text
Local Python environment
DuckDB database
Markdown reports
CSV imports
No broker order submission
```

## Phase 2: Local Dashboard

```text
Streamlit Dashboard
Localhost access only
DuckDB backend
Manual approval workflow
```

## Phase 3: Home Server or Cloud VM

```text
Scheduled daily jobs
Persistent server
Remote dashboard access
Secure authentication
Encrypted secrets
```

## Phase 4: Broker Integration

```text
Read-only first
Order draft generation second
Manual approval submission last
```

---

# 4. Recommended Local Environment

Supported OS:

- Windows 11
- macOS
- Linux

Recommended Python version:

```text
Python 3.12+
```

Recommended MVP setup:

```bash
python -m venv .venv
pip install -r requirements.txt
```

---

# 5. Repository Setup

```bash
git clone <repo-url> personal-cio-system
cd personal-cio-system
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# 6. Suggested requirements.txt

```text
pandas
numpy
duckdb
pydantic
pyyaml
python-dotenv
requests
yfinance
ta
jinja2
pytest
black
ruff
streamlit
plotly
```

Optional future dependencies:

```text
openai
langgraph
langchain
apscheduler
```

---

# 7. Environment Variables

Create:

```text
.env
```

Example:

```env
APP_ENV=local
DATABASE_PATH=data/db/personal_cio.duckdb

SCHWAB_API_ENABLED=false
SCHWAB_CLIENT_ID=
SCHWAB_CLIENT_SECRET=
SCHWAB_REDIRECT_URI=

OPENAI_API_KEY=
ORDER_SUBMISSION_ENABLED=false
```

Hard rule:

```text
Never commit .env
```

---

# 8. .gitignore

Recommended:

```gitignore
.venv/
.env
__pycache__/
*.pyc
data/db/*.duckdb
data/db/*.wal
logs/
outputs/
imports/raw/
backup/
```

---

# 9. Folder Setup

Create:

```text
personal-cio-system/
├── data/
│   ├── db/
│   ├── market/
│   ├── signals/
│   ├── reports/
│   └── journal/
├── imports/
│   ├── raw/
│   │   ├── schwab/
│   │   └── vanguard/
│   ├── normalized/
│   └── archive/
├── outputs/
│   ├── briefs/
│   ├── trade_plans/
│   ├── order_drafts/
│   └── journal/
├── logs/
└── backup/
    ├── daily/
    └── weekly/
```

---

# 10. Database Initialization

Run:

```bash
python scripts/init_db.py
```

Expected output:

```text
DuckDB created: data/db/personal_cio.duckdb
Tables created successfully.
Default symbols inserted.
Default watchlists inserted.
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

Default accounts:

```text
VANGUARD_ROTH
SCHWAB_ROTH
```

---

# 11. Configuration Files

## config/app.yaml

```yaml
app:
  name: personal-cio-system
  environment: local
  timezone: America/Chicago
  base_currency: USD
  report_format:
    - markdown
    - json
```

## config/accounts.yaml

```yaml
accounts:
  VANGUARD_ROTH:
    broker: VANGUARD
    account_type: ROTH_IRA
    account_role: CORE_PASSIVE
    individual_stock_policy: EXIT_ONLY
    order_draft_enabled: false
    api_sync_enabled: false
    csv_import_enabled: true
    default_replacement:
      VOO: 0.7
      QQQ: 0.3

  SCHWAB_ROTH:
    broker: SCHWAB
    account_type: ROTH_IRA
    account_role: ACTIVE_TRADING
    individual_stock_policy: ACTIVE_ALLOWED
    order_draft_enabled: true
    api_sync_enabled: false
```

## config/symbols.yaml

```yaml
core_index:
  - VOO
  - QQQ
  - SPY

active_watchlist:
  - MSFT
  - AAPL
  - NVDA
  - GOOGL
  - AMZN
  - META
  - VRTX
  - COST
  - AVGO
  - LLY
```

## config/risk.yaml

```yaml
risk:
  max_single_stock_weight: 0.08
  max_new_trade_weight: 0.03
  max_trade_risk_percent: 0.005
  min_risk_reward_ratio: 2.0
  block_new_entry_before_earnings_days: 5
  min_confidence_for_order_draft: 70
```

## config/broker.yaml

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
```

---

# 12. Daily Local Run

MVP command:

```bash
python scripts/run_daily_pipeline.py
```

Pipeline:

```text
1. Load config
2. Load symbol universe
3. Download market data
4. Calculate indicators
5. Generate signals
6. Generate trade plans
7. Generate order drafts if eligible
8. Generate Daily CIO Brief
9. Write journal records
10. Save outputs
```

Expected outputs:

```text
outputs/briefs/YYYY-MM-DD_Daily_CIO_Brief.md
outputs/trade_plans/YYYY-MM-DD_trade_plans.json
outputs/order_drafts/YYYY-MM-DD_order_drafts.json
outputs/journal/YYYY-MM-DD_journal.json
```

---

# 13. CSV Import Workflow

Place files:

```text
imports/raw/schwab/
imports/raw/vanguard/
```

Run import:

```bash
python scripts/import_broker_csv.py --broker schwab --file imports/raw/schwab/transactions.csv
python scripts/import_broker_csv.py --broker vanguard --file imports/raw/vanguard/transactions.csv
```

Importer flow:

```text
1. Detect file type
2. Normalize columns
3. Validate records
4. Write normalized CSV
5. Insert into DuckDB
6. Archive raw file
```

---

# 14. Streamlit Dashboard Deployment

Phase 2 command:

```bash
streamlit run apps/dashboard.py
```

Dashboard pages:

```text
Daily CIO Brief
Portfolio
Trade Plans
Order Drafts
Journal
Performance Review
Settings
```

Local URL:

```text
http://localhost:8501
```

---

# 15. Scheduled Execution

## Windows Task Scheduler

Recommended run time:

```text
After market close
5:30 PM Central Time
```

Command:

```powershell
cd C:\path\to\personal-cio-system
.\.venv\Scripts\python.exe scripts\run_daily_pipeline.py
```

## cron on macOS / Linux

```cron
30 17 * * 1-5 cd /path/to/personal-cio-system && .venv/bin/python scripts/run_daily_pipeline.py
```

---

# 16. Backup Strategy

Backup:

```text
data/db/personal_cio.duckdb
config/
outputs/
imports/normalized/
```

Do not backup raw broker files to cloud unless encrypted.

Recommended:

```text
Daily local backup
Weekly external/cloud backup
```

Backup command:

```bash
python scripts/backup_db.py
```

Expected output:

```text
backup/daily/personal_cio_YYYY-MM-DD.duckdb
```

---

# 17. Security Guidelines

Never commit:

```text
.env
API keys
OAuth tokens
Broker credentials
Raw broker CSV exports
```

Broker mode default:

```text
read_only
```

Order submission default:

```text
false
```

All broker orders must require user approval.

---

# 18. Schwab API Deployment Notes

## Phase 1

```env
SCHWAB_API_ENABLED=false
```

## Phase 2: Read-only sync

```env
SCHWAB_API_ENABLED=true
ORDER_SUBMISSION_ENABLED=false
```

## Phase 3: Approved submission only

```env
SCHWAB_API_ENABLED=true
ORDER_SUBMISSION_ENABLED=true
```

Even in Phase 3:

```text
Only approved order drafts can be submitted.
```

---

# 19. Logging

Logs:

```text
logs/app.log
logs/broker.log
logs/pipeline.log
logs/errors.log
```

Log levels:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Broker actions must always be logged.

---

# 20. Testing Before First Use

Run:

```bash
pytest
```

Required tests:

```text
Database initialization test
Market data download test
Indicator calculation test
Trade plan generation test
Order draft safety test
Vanguard exit-only rule test
Schwab active-trading rule test
Journal write test
```

---

# 21. Pre-Production Checklist

```text
[ ] .env is configured
[ ] DuckDB initialized
[ ] Default symbols inserted
[ ] Vanguard account role is CORE_PASSIVE
[ ] Schwab account role is ACTIVE_TRADING
[ ] ORDER_SUBMISSION_ENABLED=false
[ ] Broker API disabled or read-only
[ ] CSV import tested with sample files
[ ] Trade plans generated correctly
[ ] Order drafts cannot submit without approval
[ ] Backups tested
[ ] Git does not track .env or broker CSV files
```

---

# 22. Production Safety Checklist

Before enabling Schwab order submission:

```text
[ ] Schwab API read-only sync works
[ ] Order draft creation works
[ ] User approval workflow works
[ ] Rejected drafts cannot be submitted
[ ] Modified drafts are revalidated
[ ] Duplicate order protection works
[ ] Insufficient cash check works
[ ] Insufficient position check works
[ ] Broker response is stored
[ ] Order status sync works
[ ] Emergency disable flag works
```

Emergency flag:

```env
ORDER_SUBMISSION_ENABLED=false
```

---

# 23. Common Commands

Initialize database:

```bash
python scripts/init_db.py
```

Run daily pipeline:

```bash
python scripts/run_daily_pipeline.py
```

Import CSV:

```bash
python scripts/import_broker_csv.py --broker schwab --file imports/raw/schwab/transactions.csv
```

Run dashboard:

```bash
streamlit run apps/dashboard.py
```

Run tests:

```bash
pytest
```

Format code:

```bash
black .
ruff check .
```

Backup database:

```bash
python scripts/backup_db.py
```

---

# 24. Troubleshooting

## DuckDB file locked

Possible cause:

```text
Another process is using the database.
```

Solution:

```text
Close dashboard or pipeline process and retry.
```

## Market data missing

Check:

```text
Internet connection
Ticker symbol
Data provider availability
```

## CSV import failed

Check:

```text
Broker format changed
Missing columns
Encoding issue
Date format issue
```

## Order draft not generated

Check:

```text
Confidence threshold
Account role
Risk rule block
Event risk block
Action is WATCH only
```

## Vanguard buy blocked

Expected behavior:

```text
Vanguard is CORE_PASSIVE / EXIT_ONLY.
Individual stock BUY is blocked by design.
```

---

# 25. Deployment Success Criteria

Deployment is successful if:

- Local environment is installed.
- DuckDB initializes successfully.
- Daily pipeline runs end-to-end.
- Market data is stored.
- Signals are generated.
- Trade plans are generated.
- Order drafts are generated only when eligible.
- Daily CIO Brief is generated.
- Journal entries are stored.
- CSV imports work for Schwab and Vanguard.
- No order can be submitted without approval.
- Backup works.

The MVP deployment should allow the user to manage investments in 5-15 minutes per day with a safe Human-in-the-Loop process.
