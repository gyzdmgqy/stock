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

Product name: personal-cio-system.

Current repository folder: Stock. Directory name is not part of application
behavior; no repository rename is required by this plan.

# 3. Monorepo Structure

personal-cio-system/
├── docs/
├── market-data-service/
├── analysis-engine/
├── trade-planner/
├── broker-gateway/
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
├── accounts.yaml
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

MVP: DuckDB only; schema owned by doc 04.
Future storage changes require a separate design decision.

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

[Doc 10](10_TDD_Development_Plan_and_Codex_Prompts.md) is the canonical build order.
Begin with Phases 0-2 (repository, shared models/config, canonical database).
The daily runtime pipeline is defined in doc 02 and does not dictate build order.
Use fixtures for dependencies whose implementation comes in a later phase.

# 15. Success Criteria

Repository is ready when:

- Monorepo created
- Directory structure created
- Config system ready
- DuckDB initialized
- Test framework working
- First service scaffold completed

At that point development of Personal CIO System can begin.
