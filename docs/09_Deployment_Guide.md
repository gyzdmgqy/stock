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
streamlit>=1.50,<2
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
SCHWAB_ACCESS_TOKEN=
SCHWAB_ACCESS_TOKEN_EXPIRES_AT=
SCHWAB_ACCOUNT_NUMBER=

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

在仓库根目录、使用同一个 Python 虚拟环境启动：

```bash
python -m streamlit run apps/dashboard.py --server.address 127.0.0.1
```

访问 [127.0.0.1:8501](http://127.0.0.1:8501)。数据库路径与日流程一致，`DATABASE_PATH` 可覆盖默认位置；未初始化时仪表盘不会新建数据库。仅允许环回地址，保留 XSRF 和 CORS 保护，不支持远程访问或发布。

七页包括每日 CIO 简报、组合持仓、交易计划、订单草稿、投资日志、绩效复盘和只读设置。简报是生成时的记录，实时审批状态以订单草稿页为准。组合页面按所选业务日期读取快照，保留未知现金和实际零值的区别；绩效页只展示已入库的复盘和结果，不推测缺失值。

订单草稿页可批准、拒绝或延期；延期后可先恢复待审再批准。批准要求人工核对完整订单参数，由网关重新校验计划时效、仓位或资金，以及账户和券商权限。若页面显示的版本已变更，须重新审阅。草稿状态、`approval_record` 和对应 `journal_entry` 同事务写入，日志按芝加哥业务日期记录。没有券商 API 接入或订单提交操作。

浏览使用短连接，审批后关闭写连接；不要与 CSV 导入或日流程同时写同一数据库。设置页不展示凭据，也不能编辑风控或券商配置。

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

先用本地数据验证券商 CSV 导入、日流程和仪表盘。默认不联网同步；首次真实读取须由用户完成本地验收并单独启用。测试不需要真实凭据。Schwab 的产品权限见[官方个人 Trader API 门户](https://developer.schwab.com/products/trader-api--individual)。

确认要启用时，参考 `.env.example`，只在本机环境或 Git 忽略的 `.env` 配置：

```env
SCHWAB_API_ENABLED=true
ORDER_SUBMISSION_ENABLED=false
SCHWAB_ACCESS_TOKEN=
SCHWAB_ACCESS_TOKEN_EXPIRES_AT=
SCHWAB_ACCOUNT_NUMBER=
```

访问令牌须由外部流程取得；到期时间为带时区的 ISO 时间，账号要与目标本地账户对应。不要把真实值放进命令行参数、聊天或 Git。本阶段不存在登录回调、刷新令牌或定时同步。

确认 `config/broker.yaml` 中 Schwab 启用、模式为 `read_only`、提交为 `false`。在 `config/accounts.yaml` 仅对确认绑定的 Schwab 账户启用 `api_sync_enabled`；已初始化的数据库还须单独核对并更新对应账户的同名权限。初始化不会覆盖旧账号的设置，CLI 也不会替你启用。

```powershell
# 仅在上述条件已满足时运行
.\.venv\Scripts\python.exe scripts/sync_schwab_read_only.py --confirm-local-acceptance
# --since 增加成交读取；--orders 增加只读订单状态
```

有重叠歧义时，改用不重叠的成交窗口，或不传 `--since` 只同步持仓和现金。同步不会替代手工可卖股数、挂单状态或组合暴露证据，也不要与 CSV 导入或日流程并发写入同一数据库。

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

运行本地仪表盘：

```bash
python -m streamlit run apps/dashboard.py --server.address 127.0.0.1
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
