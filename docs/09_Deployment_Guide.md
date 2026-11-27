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
- Schwab read-only API only after local CSV, pipeline, and dashboard are stable
- Future order draft approval workflow
- Safe handling of broker credentials
- Easy backup and recovery

---

# 3. Deployment Milestones

[Doc 10](10_TDD_Development_Plan_and_Codex_Prompts.md) is the canonical execution
plan. Deployment milestones use its phase numbers.

| Build phases | Deployment |
|---|---|
| 0-9 | Local Python, DuckDB, reports, CSV imports, and order draft/approval services |
| 10 | Verified end-to-end daily pipeline |
| 11 | Localhost-only Streamlit dashboard with manual approval workflow |
| 12 | Schwab read-only API, after CSV, pipeline, and dashboard are stable |
| 13 | Approved Schwab submission after read-only integration is verified |

Home-server/cloud deployment is optional future work. Remote access would need
its own authentication and secrets design; it is not a prerequisite for Phase 12.
Vanguard remains CSV import and manual execution.

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
exchange-calendars>=4.11,<5
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
imports/
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

Doc 04 is the only schema authority. Account settings live in accounts.yaml;
broker capabilities live in broker.yaml. Both must allow an action. The global
ORDER_SUBMISSION_ENABLED flag can disable submission but cannot bypass either.

## config/app.yaml

```yaml
app:
  name: personal-cio-system
  environment: local
  timezone: America/Chicago
  base_currency: USD
  market_history_sessions: 220
  report_format:
    - markdown
    - json
```

America/Chicago is fixed for the application and scheduler, including during
travel. Never infer it from the host timezone. Persist UTC instants and use
exchange-session dates as specified in doc 04.

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
    default_replacement: null  # Allocation is undecided; no implicit 70/30 default

  SCHWAB_ROTH:
    broker: SCHWAB
    account_type: ROTH_IRA
    account_role: ACTIVE_TRADING
    individual_stock_policy: ACTIVE_ALLOWED
    order_draft_enabled: true
    api_sync_enabled: false
```

Replacement ratios elsewhere in the docs are examples only. A null allocation
allows exit monitoring but leaves replacement amounts unallocated.

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
  max_combined_symbol_weight: 0.08
  max_combined_sector_weight: 0.25
  min_risk_reward_ratio: 2.0
  block_new_entry_before_earnings_days: 5
  min_entry_confidence_for_order_draft: 70
```

仓位和单笔风险按单账户净值计算；组合单标的默认上限为 8%，板块为 25%，分别校验。入场置信度只用于 ADD / RE_ENTRY。REDUCE / EXIT 使用单独的退出规则，所需小时确认不可绕过。

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

在初始化 DuckDB 并导入最新券商 CSV 后，从仓库根目录运行：

```bash
python scripts/run_daily_pipeline.py
# 不联网，只使用 DuckDB 已有的行情
python scripts/run_daily_pipeline.py --offline
```

`--db-path`、`--config-dir`、`--output-dir` 可指定其他位置。未指定数据库时读取 `DATABASE_PATH` 或使用默认路径。业务日期固定按 `America/Chicago` 计算，常规交易时段、休市和提前收市以 XNYS 日历为准。非交易日或尚未收盘时直接跳过，不下载、不写入。

默认只通过 yfinance 补齐窗口内缺少或不完整的日线，保留完整的本地数据。默认分析窗口为 220 个交易日，额外读取一日供前一交易日指标复算。缺少当日行情时不借用旧信号；窗口不全时可生成信号，但该标的本次不生成计划和草稿。已有历史记录保留，简报仅展示本次使用的信号和计划。

运行顺序：

```text
行情 → 指标和信号 → 交易计划 → 待审订单草稿 → CIO 简报 → 投资日志
```

券商 CSV 只能证明记录中的事实。CSV 缺行不等于空仓，现金余额不等于可交易现金，持有股数不等于可卖股数。净值优先使用当日已记录的组合风险快照；挂单状态、可卖股数及其他策略证据缺失或过期时，会在简报提示，不会据此生成草稿。

可选人工确认文件默认位于 Git 忽略的 `imports/normalized/planning.yaml`，也可用 `--planning-inputs` 指定。仅填写实际确认过的事实。下面是合成示例：

```yaml
reviews:
  - account_id: SCHWAB_ROTH
    symbol: VRTX
    observed_at: "2026-06-08T15:00:00-05:00"
    has_open_order: false
    available_to_sell: 5
    exit_limit_price: 89
```

入场还要满足原规划条件。需要时可附实际确认的 `confirmed_flat`、`reentry_candidate`、`earnings_checked_through`、`entry_prices`、`intraday_signal` 和组合暴露；系统不会从小时价格推断确认，也不会从没有事件记录推断财报日历已覆盖。账户和券商配置两者都须开放草稿，流程不会自动批准、下单或连接券商 API。

输出文件：

```text
outputs/briefs/YYYY-MM-DD_Daily_CIO_Brief.md
outputs/briefs/YYYY-MM-DD_Daily_CIO_Brief.json
outputs/trade_plans/YYYY-MM-DD_trade_plans.json
outputs/order_drafts/YYYY-MM-DD_order_drafts.json
outputs/journal/YYYY-MM-DD_journal.json
```

每日简报以 DuckDB 中的记录为准。同日、同一输入重跑不重复写入信号、计划、草稿或日志，保留原简报 ID、创建时间和人工备注；输入修正允许生成可追溯的新版本。各阶段使用自身事务，输出文件单独原子替换；中断后重跑即可补齐。不要与 CSV 导入或其他写入流程并发运行。

---

# 13. CSV Import Workflow

Place files:

```text
imports/raw/schwab/
imports/raw/vanguard/
```

按[券商 CSV 使用说明](../broker-gateway/README.md)设置本地模块路径，再运行导入命令。例如 Windows PowerShell：

```powershell
$env:PYTHONPATH = "broker-gateway/src;investment-journal/src;."
.\.venv\Scripts\python.exe -m broker_gateway.csv_import SCHWAB SCHWAB_ROTH imports/raw/schwab/transactions.csv
.\.venv\Scripts\python.exe -m broker_gateway.csv_import VANGUARD VANGUARD_ROTH imports/raw/vanguard/transactions.csv
```

预览确认前不写入数据库，确认并成功提交后才归档。持仓和现金导入必须附实际的 `--observed-at`。

---

# 14. Streamlit Dashboard Deployment

Phase 11 command:

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
5:30 PM America/Chicago, after a completed market session
```

Command:

```powershell
cd C:\path\to\personal-cio-system
.\.venv\Scripts\python.exe scripts\run_daily_pipeline.py
```

Configure the scheduler with an explicit America/Chicago timezone and daylight
saving behavior. A host-local 17:30 trigger is insufficient on a travel laptop.
Skip non-trading sessions and incomplete bars using the exchange calendar.

## cron on macOS / Linux

Only use this example where the scheduler supports CRON_TZ; otherwise configure
an explicitly timezone-aware scheduler. Do not silently fall back to host time.

```cron
CRON_TZ=America/Chicago
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

Broker data in raw, normalized, archived, database, and report form is private.
Encrypt any cloud backups containing it. Perform consistent backups while the
coordinated writer is quiescent and test restoration.

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

## Local MVP (Phases 0-11)

```env
SCHWAB_API_ENABLED=false
```

## Phase 12: Read-only sync

```env
SCHWAB_API_ENABLED=true
ORDER_SUBMISSION_ENABLED=false
```

## Phase 13: Approved submission only

```env
SCHWAB_API_ENABLED=true
ORDER_SUBMISSION_ENABLED=true
```

Even in Phase 13:

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
[ ] Modified drafts create a fresh draft and require new approval
[ ] UNKNOWN submission outcomes reconcile without blind retries
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

导入 CSV 见[第 13 节](#13-csv-import-workflow)。

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

Phase 3 可按[行情服务说明](../market-data-service/README.md)下载并查询日线。
收到 `DATA_MISSING` 时，先检查标的代码、所选区间是否包含交易日，以及数据源
是否覆盖该区间。yfinance 在限流时会返回可重试错误，可降低频率后重试。

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
Entry confidence threshold or protective-exit eligibility
Required hourly confirmation
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
