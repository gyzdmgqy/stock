# Personal CIO System
## TDD Development Plan & Codex Prompt Playbook V1.0

---

# 1. Why TDD is a Good Fit

TDD is strongly recommended for this project.

Personal CIO System is not a pure UI project. It is a rule-driven investment decision system where correctness, auditability, and safety matter more than speed of coding.

TDD is especially suitable because the system has many deterministic rules:

- Vanguard account must be CORE_PASSIVE / EXIT_ONLY.
- Schwab account must be ACTIVE_TRADING.
- No order can be submitted without explicit approval.
- Confidence below threshold must not generate an order draft.
- Daily signals drive direction.
- Hourly signals improve execution.
- Every trade plan must have invalid conditions.
- Every order draft must trace back to a trade plan.
- Every journal entry must preserve decision context.

These rules can and should be tested before implementation.

---

# 2. Development Principle

Use the following loop for every feature:

```text
1. Read docs
2. Write failing tests
3. Implement minimal code
4. Run tests
5. Refactor
6. Commit
```

Codex should not start by writing production code first.

Every Codex task should explicitly say:

```text
Follow TDD:
- create or update tests first
- confirm tests fail for the expected reason
- implement minimal code
- run tests
- refactor without changing behavior
```

---

# 3. Recommended Development Order

The project should not start with Schwab API or Agent orchestration.

Recommended order:

```text
Phase 0: Repository Foundation
Phase 1: Shared Models and Config
Phase 2: DuckDB Database Initialization
Phase 3: Market Data Service
Phase 4: Analysis Engine
Phase 5: Trade Planner
Phase 6: Investment Journal
Phase 7: Personal CIO Brief Generator
Phase 8: Broker Gateway CSV Import
Phase 9: Broker Gateway Order Draft Safety
Phase 10: Streamlit Dashboard / CLI
Phase 11: Schwab Read-Only API
Phase 12: Approved Order Submission
```

---

# 4. Global Codex System Prompt

Use this prompt at the beginning of every new Codex session.

```text
You are developing the Personal CIO System.

This is a local-first, single-user, Human-in-the-Loop investment decision assistant.

Before writing code, read these docs under docs/:

- 01_Product_Requirements.md
- 02_System_Architecture.md
- 03_Repository_Bootstrap_Plan.md
- 04_Database_Design.md
- 05_Agent_Communication_Protocol.md
- 06_Trade_Planner_Design.md
- 07_Broker_Gateway_Design.md
- 08_Investment_Journal_Design.md
- 09_Deployment_Guide.md

Follow these non-negotiable rules:

1. Use TDD.
2. Write or update tests before production code.
3. Keep the MVP local-first.
4. Use DuckDB as the MVP database.
5. Do not implement automatic trading.
6. No broker order submission without explicit human approval.
7. Vanguard Roth IRA is CORE_PASSIVE and EXIT_ONLY for individual stocks.
8. Schwab Roth IRA is ACTIVE_TRADING.
9. Trade Planner is rule-driven; agents explain but do not decide.
10. Every trade plan must be structured, explainable, and auditable.
11. All generated records must be traceable by IDs.
12. Do not commit secrets, tokens, broker CSVs, database files, or .env files.

Use Python 3.12+, pytest, pydantic, duckdb, pyyaml, and python-dotenv.

When implementing a feature:
- explain the test cases first
- write failing tests
- implement minimal code
- run tests
- show test results
- keep changes small
```

---

# 5. Phase 0 — Repository Foundation

## Goal

Create the monorepo skeleton and development tooling.

## Expected Output

```text
personal-cio-system/
├── docs/
├── shared/
├── market-data-service/
├── analysis-engine/
├── trade-planner/
├── broker-gateway-schwab/
├── personal-cio-agent/
├── investment-journal/
├── config/
├── scripts/
├── tests/
├── data/
├── outputs/
├── imports/
├── logs/
├── backup/
├── requirements.txt
├── pyproject.toml
├── .gitignore
└── README.md
```

## Tests

- Verify required directories exist.
- Verify config files can be loaded.
- Verify `.env` is not required for basic tests.
- Verify pytest can run.

## Codex Prompt

```text
Implement Phase 0: Repository Foundation for Personal CIO System.

Read docs/03_Repository_Bootstrap_Plan.md and docs/09_Deployment_Guide.md first.

Follow TDD.

Tasks:
1. Create the monorepo folder structure described in the docs.
2. Add requirements.txt with MVP dependencies.
3. Add pyproject.toml configured for pytest, black, and ruff.
4. Add .gitignore that excludes .env, DuckDB files, logs, outputs, raw imports, backups, and virtual environments.
5. Add sample config files:
   - config/app.yaml
   - config/accounts.yaml
   - config/symbols.yaml
   - config/risk.yaml
   - config/broker.yaml
6. Add tests/test_repository_structure.py that verifies required folders and config files exist.
7. Run pytest and ensure tests pass.

Do not implement business logic yet.
```

---

# 6. Phase 1 — Shared Models and Enums

## Goal

Create common Pydantic models and enums used across modules.

## Key Models

- Symbol
- DailyPrice
- IntradayPrice
- DailySignal
- IntradaySignal
- PortfolioSnapshot
- BrokerTransaction
- TradePlan
- OrderDraft
- ApprovalDecision
- JournalEntry
- DailyCioBrief

## Tests

- Models validate required fields.
- Invalid enum values fail.
- Default statuses are correct.
- TradePlan requires invalid conditions for actionable plans.
- OrderDraft defaults to PENDING_REVIEW.

## Codex Prompt

```text
Implement Phase 1: Shared Models and Enums.

Read:
- docs/04_Database_Design.md
- docs/05_Agent_Communication_Protocol.md
- docs/06_Trade_Planner_Design.md
- docs/07_Broker_Gateway_Design.md
- docs/08_Investment_Journal_Design.md

Follow TDD.

Tasks:
1. Create shared/enums/ with account role, action, strategy type, order type, order status, broker, transaction type, message type.
2. Create shared/models/ with Pydantic models:
   - DailyPrice
   - IntradayPrice
   - DailySignal
   - IntradaySignal
   - PortfolioSnapshot
   - BrokerTransaction
   - TradePlan
   - OrderDraft
   - ApprovalDecision
   - JournalEntry
   - DailyCioBrief
3. Create unit tests under tests/unit/shared/ to validate:
   - enum constraints
   - required fields
   - default statuses
   - invalid values fail validation
   - Vanguard account role can be represented as CORE_PASSIVE
   - Schwab account role can be represented as ACTIVE_TRADING
4. Keep models broker-neutral where possible.
5. Run pytest.

Do not implement database persistence yet.
```

---

# 7. Phase 2 — DuckDB Database Initialization

## Goal

Create the MVP DuckDB schema and initialization script.

## Key File

```text
scripts/init_db.py
```

## Tests

- Database file is created in a temporary test path.
- All required tables exist.
- Default symbols are inserted.
- Default accounts are inserted.
- Running init twice is idempotent.

## Codex Prompt

```text
Implement Phase 2: DuckDB Database Initialization.

Read docs/04_Database_Design.md carefully.

Follow TDD.

Tasks:
1. Write tests first under tests/unit/database/test_init_db.py.
2. Tests should use a temporary DuckDB path, not the real data/db path.
3. Implement scripts/init_db.py and a reusable database module under shared/db/.
4. Create tables from docs/04_Database_Design.md, including:
   - symbol
   - watchlist
   - watchlist_symbol
   - daily_price
   - intraday_price
   - daily_indicator
   - daily_signal
   - signal_detail
   - portfolio_account
   - portfolio_position_snapshot
   - portfolio_risk_snapshot
   - broker_transaction
   - trade_plan
   - trade_plan_signal_link
   - order_draft
   - approval_record
   - daily_cio_brief
   - journal_entry
   - trade_outcome
   - performance_review
   - backtest_run
   - backtest_trade
   - backtest_metric
5. Insert default symbols:
   SPY, QQQ, VOO, MSFT, AAPL, NVDA, GOOGL, AMZN, META, VRTX, COST, AVGO, LLY.
6. Insert default accounts:
   - VANGUARD_ROTH: CORE_PASSIVE
   - SCHWAB_ROTH: ACTIVE_TRADING
7. Make init idempotent.
8. Run pytest.

Do not implement market data download yet.
```

---

# 8. Phase 3 — Market Data Service

## Goal

Download and store daily and optional hourly market data.

## MVP Scope

- Daily OHLCV first.
- Intraday 1h schema supported.
- Use yfinance initially.
- Store in DuckDB.

## Tests

- Normalize provider data to DailyPrice.
- Upsert avoids duplicates.
- Missing ticker returns structured error.
- Daily prices can be queried back.

## Codex Prompt

```text
Implement Phase 3: Market Data Service.

Read:
- docs/04_Database_Design.md
- docs/05_Agent_Communication_Protocol.md
- docs/09_Deployment_Guide.md

Follow TDD.

Tasks:
1. Write tests first under tests/unit/market_data/.
2. Create market-data-service/src/ with:
   - providers/yfinance_provider.py
   - services/daily_price_service.py
   - repositories/daily_price_repository.py
   - repositories/intraday_price_repository.py
3. Implement provider abstraction so yfinance can be replaced later.
4. Implement daily OHLCV normalization.
5. Implement DuckDB upsert for daily_price.
6. Implement query functions:
   - get_daily_prices(symbol, start, end)
   - get_latest_daily_price(symbol)
7. Add placeholder support for intraday_price interval='1h', but do not overbuild.
8. Use structured errors rather than silent failures.
9. Run pytest.

Do not implement indicators yet.
```

---

# 9. Phase 4 — Analysis Engine

## Goal

Convert price data into indicators and signals.

## MVP Scope

- MA5 / MA10 / MA20 / MA30 / MA50 / MA100 / MA200
- ATR14
- RSI14
- Volume averages
- Market regime
- Price vs MA200
- False breakdown score
- Volume confirmation score

## Tests

- MA calculation correctness.
- Price near MA200 classification.
- False breakdown detection.
- Long lower shadow detection.
- Volume confirmation score.
- Daily signal generated from sample candles.

## Codex Prompt

```text
Implement Phase 4: Analysis Engine.

Read:
- docs/04_Database_Design.md
- docs/05_Agent_Communication_Protocol.md
- docs/06_Trade_Planner_Design.md

Follow TDD.

Tasks:
1. Write tests first under tests/unit/analysis_engine/.
2. Create analysis-engine/src/ with:
   - indicators/moving_average.py
   - indicators/volatility.py
   - indicators/volume.py
   - signals/market_regime.py
   - signals/false_breakdown.py
   - signals/volume_confirmation.py
   - signals/gap_analysis.py
   - services/signal_service.py
3. Implement deterministic indicator functions using pandas.
4. Implement false breakdown logic:
   - intraday or daily low below MA200
   - close back above MA200
   - long lower shadow
   - volume not panic-level
5. Implement volume confirmation logic:
   - up day volume > avg5
   - up day volume > previous down day volume
   - close near high
6. Generate DailySignal Pydantic objects.
7. Persist daily_indicator and daily_signal to DuckDB.
8. Add signal_detail records for explainability.
9. Run pytest.

Do not implement Trade Planner yet.
```

---

# 10. Phase 5 — Trade Planner

## Goal

Generate structured, human-reviewable trade plans.

## Critical Rules

- Vanguard individual stocks are EXIT_ONLY.
- Schwab active trading can generate ADD / REDUCE / EXIT / RE_ENTRY.
- Confidence below threshold does not generate order draft.
- WATCH usually does not generate order draft.
- Every plan must have invalid conditions.
- Daily direction, hourly execution.

## Tests

- Vanguard BUY individual stock is blocked.
- Vanguard existing individual stock gets EXIT_ONLY plan.
- Schwab high-confidence RE_ENTRY gets valid TradePlan.
- Confidence < 50 creates no actionable plan.
- Confidence 70+ is eligible for order draft.
- Earnings window blocks new entry.
- Invalid condition is required.

## Codex Prompt

```text
Implement Phase 5: Trade Planner.

Read docs/06_Trade_Planner_Design.md very carefully.
Also read docs/05_Agent_Communication_Protocol.md and docs/04_Database_Design.md.

Follow TDD.

Tasks:
1. Write tests first under tests/unit/trade_planner/.
2. Create trade-planner/src/ with:
   - planners/base.py
   - planners/vanguard_exit_planner.py
   - planners/schwab_active_planner.py
   - rules/account_role_gate.py
   - rules/confidence_gate.py
   - rules/event_risk_gate.py
   - sizing/position_sizing.py
   - services/trade_plan_service.py
3. Implement account role gate:
   - VANGUARD_ROTH CORE_PASSIVE blocks new individual stock BUY.
   - VANGUARD_ROTH allows EXIT_ONLY plans.
   - SCHWAB_ROTH ACTIVE_TRADING allows active plans.
4. Implement confidence gate:
   - <50 no order draft eligibility
   - 50-69 WATCH/small plan
   - >=70 eligible for order draft
5. Implement Vanguard Exit-Only plan generation with VOO/QQQ replacement.
6. Implement Schwab false breakdown re-entry plan generation.
7. Ensure every actionable plan includes invalid_condition.
8. Persist trade_plan records to DuckDB.
9. Run pytest.

Do not implement broker submission.
```

---

# 11. Phase 6 — Investment Journal

## Goal

Record signals, plans, decisions, transactions, and outcomes.

## Tests

- Journal entry can be created from trade plan.
- Approval decision creates journal entry.
- Broker transaction links to plan.
- Outcome 5d/20d/60d can be calculated from price data.
- Rejected plans can still be evaluated.
- Vanguard migration progress can be tracked.

## Codex Prompt

```text
Implement Phase 6: Investment Journal.

Read docs/08_Investment_Journal_Design.md.
Also read docs/04_Database_Design.md.

Follow TDD.

Tasks:
1. Write tests first under tests/unit/investment_journal/.
2. Create investment-journal/src/ with:
   - services/journal_service.py
   - services/outcome_service.py
   - services/performance_review_service.py
   - repositories/journal_repository.py
   - reports/weekly_review.py
   - reports/monthly_review.py
3. Implement journal entry creation from:
   - TradePlan
   - OrderDraft
   - ApprovalDecision
   - BrokerTransaction
   - DailyCioBrief
4. Implement trade_outcome calculation for 5d, 20d, 60d if price data exists.
5. Implement benchmark comparison placeholders for VOO, QQQ, SPY.
6. Implement weekly review skeleton.
7. Persist journal_entry, trade_outcome, performance_review.
8. Run pytest.

Do not implement UI yet.
```

---

# 12. Phase 7 — Daily CIO Brief Generator

## Goal

Generate the daily Markdown and JSON brief.

## Tests

- Brief includes market summary.
- Brief includes portfolio summary.
- Brief includes risk summary.
- Brief includes trade plan summary.
- Brief includes order draft summary.
- Brief includes final recommendation.
- Markdown file is generated.
- JSON payload is generated.

## Codex Prompt

```text
Implement Phase 7: Personal CIO Brief Generator.

Read:
- docs/05_Agent_Communication_Protocol.md
- docs/08_Investment_Journal_Design.md
- docs/09_Deployment_Guide.md

Follow TDD.

Tasks:
1. Write tests first under tests/unit/personal_cio_agent/.
2. Create personal-cio-agent/src/ with:
   - brief_generator/daily_brief.py
   - templates/daily_cio_brief.md.j2
   - services/brief_service.py
3. Generate Daily CIO Brief from structured data:
   - market summary
   - portfolio summary
   - risk summary
   - trade plans
   - order drafts
   - journal reminders
   - final recommendation
4. Output both Markdown and JSON.
5. Store daily_cio_brief record in DuckDB.
6. Save files under outputs/briefs/.
7. Run pytest.

Keep LLM integration optional. Use deterministic template first.
```

---

# 13. Phase 8 — Broker Gateway CSV Import

## Goal

Import Schwab and Vanguard positions / transactions via CSV.

## Tests

- Schwab transaction CSV maps to BrokerTransaction.
- Vanguard transaction CSV maps to BrokerTransaction.
- CSV normalization handles missing optional fields.
- Duplicate transactions are not inserted twice.
- Raw files are not committed.
- Import creates journal records.

## Codex Prompt

```text
Implement Phase 8: Broker Gateway CSV Import.

Read:
- docs/07_Broker_Gateway_Design.md
- docs/04_Database_Design.md
- docs/08_Investment_Journal_Design.md

Follow TDD.

Tasks:
1. Write tests first under tests/unit/broker_gateway/csv_import/.
2. Create broker-gateway-schwab/src/csv_import/ with:
   - base_importer.py
   - schwab_transaction_importer.py
   - vanguard_transaction_importer.py
   - normalizer.py
   - validators.py
3. Implement normalized BrokerTransaction output.
4. Insert transactions into broker_transaction table.
5. Prevent duplicate imports.
6. Archive imported files after successful import.
7. Generate journal entries for imported executions.
8. Run pytest.

Do not connect Schwab API yet.
```

---

# 14. Phase 9 — Order Draft Safety

## Goal

Convert eligible trade plans into broker-neutral order drafts.

## Tests

- No draft without eligible action.
- No draft when confidence below threshold.
- No Vanguard individual BUY draft.
- No duplicate draft.
- BUY checks estimated cash if cash data exists.
- SELL checks position quantity if position data exists.
- Draft status defaults to PENDING_REVIEW.
- Approval required before submission-ready state.

## Codex Prompt

```text
Implement Phase 9: Broker Gateway Order Draft Safety.

Read:
- docs/07_Broker_Gateway_Design.md
- docs/06_Trade_Planner_Design.md
- docs/05_Agent_Communication_Protocol.md

Follow TDD.

Tasks:
1. Write tests first under tests/unit/broker_gateway/order_drafts/.
2. Create broker-gateway-schwab/src/drafts/ with:
   - order_draft_service.py
   - order_draft_validator.py
   - duplicate_detector.py
3. Implement conversion from TradePlan to broker-neutral OrderDraft.
4. Enforce safety rules:
   - no automatic submission
   - user approval required
   - Vanguard individual BUY blocked
   - confidence threshold enforced
   - duplicate draft blocked
5. Persist order_draft to DuckDB.
6. Implement approval_record creation but not broker submission.
7. Run pytest.

Do not call Schwab API.
```

---

# 15. Phase 10 — End-to-End Daily Pipeline

## Goal

Run the entire local pipeline from data to brief.

## Tests

- Pipeline runs with sample data.
- Signals generated.
- Trade plans generated.
- Order drafts generated only when eligible.
- Brief generated.
- Journal entries created.
- Pipeline is idempotent for the same date.

## Codex Prompt

```text
Implement Phase 10: End-to-End Daily Pipeline.

Read docs/09_Deployment_Guide.md.

Follow TDD.

Tasks:
1. Write integration tests under tests/integration/test_daily_pipeline.py.
2. Implement scripts/run_daily_pipeline.py.
3. Pipeline should:
   - load config
   - load symbols
   - load or download price data
   - calculate indicators
   - generate signals
   - generate trade plans
   - generate order drafts when eligible
   - generate Daily CIO Brief
   - create journal entries
4. Use sample data in tests to avoid network dependency.
5. Ensure pipeline can run repeatedly without duplicate records.
6. Run pytest.

Do not implement Schwab API yet.
```

---

# 16. Phase 11 — Streamlit Dashboard

## Goal

Create local dashboard for review.

## Pages

- Daily CIO Brief
- Portfolio
- Trade Plans
- Order Drafts
- Journal
- Performance Review
- Settings

## Tests

Streamlit is hard to unit test fully, so test underlying services.

## Codex Prompt

```text
Implement Phase 11: Local Streamlit Dashboard.

Read docs/09_Deployment_Guide.md.

Follow TDD for service functions.

Tasks:
1. Create apps/dashboard.py.
2. Create pages:
   - Daily CIO Brief
   - Portfolio
   - Trade Plans
   - Order Drafts
   - Journal
   - Performance Review
   - Settings
3. Dashboard should read from DuckDB.
4. It should not submit broker orders.
5. Order drafts can be marked APPROVED / REJECTED / DEFERRED locally.
6. Approval decisions must be written to approval_record and journal_entry.
7. Add tests for approval service, not necessarily Streamlit UI.
8. Run pytest.
```

---

# 17. Phase 12 — Schwab Read-Only API

## Goal

Connect Schwab only in read-only mode.

## Tests

Use mocks, not live API.

## Codex Prompt

```text
Implement Phase 12: Schwab Read-Only API Integration.

Read docs/07_Broker_Gateway_Design.md and docs/09_Deployment_Guide.md.

Follow TDD.

Tasks:
1. Write tests with mocked Schwab API responses.
2. Implement auth metadata handling without committing secrets.
3. Implement account read.
4. Implement position read.
5. Implement transaction/order status read if available.
6. Store normalized PortfolioSnapshot and BrokerTransaction records.
7. Ensure ORDER_SUBMISSION_ENABLED=false by default.
8. Add tests proving no submit function can run in read-only mode.
9. Run pytest.

Do not implement order submission yet.
```

---

# 18. Phase 13 — Approved Order Submission

## Goal

Only after the system is stable, allow approved Schwab order submission.

## Tests

All tests must use mocks.

## Codex Prompt

```text
Implement Phase 13: Approved Schwab Order Submission.

Read docs/07_Broker_Gateway_Design.md.

Follow TDD.

Safety is critical.

Tasks:
1. Write tests first proving:
   - rejected drafts cannot submit
   - pending drafts cannot submit
   - modified drafts must be revalidated
   - ORDER_SUBMISSION_ENABLED=false blocks submission
   - no approval record blocks submission
   - insufficient cash blocks BUY
   - insufficient position blocks SELL
   - duplicate submission is blocked
2. Implement submit_approved_order using mocked broker adapter first.
3. Require:
   - draft.status == APPROVED
   - approval_record exists
   - ORDER_SUBMISSION_ENABLED == true
   - account role allows action
   - risk validation passes
4. Store broker response.
5. Update order status.
6. Create journal entry.
7. Run pytest.

Do not use live order submission until manual review outside Codex.
```

---

# 19. Recommended Commit Plan

Each phase should be committed separately.

Example commits:

```text
chore(repo): initialize monorepo structure
feat(shared): add pydantic models and enums
feat(db): initialize duckdb schema
feat(market-data): add daily price ingestion
feat(analysis): add indicators and signal generation
feat(trade-planner): add account-aware trade planning
feat(journal): add investment journal and outcome tracking
feat(cio): generate daily cio brief
feat(broker): import schwab and vanguard csv transactions
feat(broker): add safe order draft generation
feat(pipeline): add end-to-end daily pipeline
feat(ui): add local streamlit dashboard
```

---

# 20. Codex Task Template

Use this template for future tasks.

```text
Task: <task name>

Context:
- Read docs/<relevant docs>.
- Follow existing project structure.
- Follow TDD.

Requirements:
1. Write tests first.
2. Do not break existing tests.
3. Implement minimal production code.
4. Keep the change scoped.
5. Use Pydantic models from shared/.
6. Persist data to DuckDB only if required.
7. Add or update documentation if behavior changes.
8. Run pytest.

Safety Rules:
- No automatic trading.
- No broker submission without explicit approval.
- Vanguard individual stock BUY must remain blocked.
- Schwab active trading must still require human approval.

Expected Output:
- Tests added
- Code added
- Tests passing
- Summary of files changed
```

---

# 21. Immediate Next Step

Start with Phase 0 and Phase 1.

Do not start with:

- Schwab API
- LLM Agent
- Streamlit UI
- Order submission

The correct first milestone is:

```text
Repo scaffold + shared models + DuckDB schema + tests passing
```

Once that is done, the rest of the system can be built safely and incrementally.
