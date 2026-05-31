# Personal CIO System
## Repository Bootstrap Plan V1.0

# 1. Purpose

Defines repository structure, coding conventions, development workflow and bootstrap plan.

Goals:
- Standardize development
- Support Codex/Cursor/Copilot
- Reduce architectural drift
- Enable long-term maintainability

# 2. Repository Strategy

V1 Recommendation: Monorepo

Reason:
- Single developer
- Easier debugging
- Easier AI-assisted development
- Easier deployment

Repository Name:

personal-cio-system

# 3. Monorepo Structure

personal-cio-system/
├── docs/
├── market-data-service/
├── analysis-engine/
├── trade-planner/
├── broker-gateway-schwab/
├── personal-cio-agent/
├── investment-journal/
├── shared/
├── config/
├── scripts/
├── tests/
├── data/
└── .env

# 4. Service Layout

service-name/
├── src/
├── tests/
├── config/
├── README.md
└── pyproject.toml

# 5. Shared Module

shared/
├── models/
├── enums/
├── schemas/
├── utils/
└── constants/

# 6. Configuration Strategy

config/
├── app.yaml
├── broker.yaml
├── symbols.yaml
├── risk.yaml
└── logging.yaml

Sensitive values stored in:

.env

# 7. Data Storage

data/
├── market/
├── signals/
├── reports/
├── journal/
└── db/

Database:

Phase 1:
- DuckDB

Phase 2:
- PostgreSQL

# 8. Testing Convention

Framework:
pytest

Structure:

tests/
├── unit/
├── integration/
└── regression/

Coverage Target:
80%+

# 9. Logging Convention

Levels:
- DEBUG
- INFO
- WARNING
- ERROR

logs/
├── app.log
├── trades.log
└── broker.log

# 10. Git Workflow

Branches:

main
develop
feature/*

Example:

feature/false-breakdown-agent

# 11. Commit Convention

Format:

type(scope): description

Examples:

feat(trade-planner): add stop limit generation

fix(broker): correct schwab auth

docs(architecture): update data flow

# 12. Coding Standards

Language:
Python 3.12+

Requirements:
- PEP8
- Type Hints
- Pydantic Models

Tools:
- ruff
- black

# 13. AI Development Workflow

1. Update documentation
2. Create task
3. Generate code via Codex
4. Run tests
5. Review manually
6. Commit

Rule:

Documentation drives implementation.

# 14. Initial Development Order

1. market-data-service
2. analysis-engine
3. trade-planner
4. investment-journal
5. personal-cio-agent
6. broker-gateway-schwab

# 15. Success Criteria

Repository is ready when:

- Monorepo created
- Directory structure created
- Config system ready
- DuckDB initialized
- Test framework working
- First service scaffold completed

At that point development of Personal CIO System can begin.
