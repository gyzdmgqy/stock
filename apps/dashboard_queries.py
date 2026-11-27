from dataclasses import dataclass
from datetime import date

from duckdb import DuckDBPyConnection

from broker_gateway.drafts import OrderDraftService
from personal_cio_agent.services.brief_service import BriefService
from shared.db import get_trade_plan
from shared.enums import OrderDraftStatus

_DATES = {
    "brief": "SELECT DISTINCT brief_date AS day FROM daily_cio_brief",
    "portfolio": (
        "SELECT snapshot_date AS day FROM portfolio_position_snapshot UNION "
        "SELECT snapshot_date FROM portfolio_cash_snapshot UNION "
        "SELECT snapshot_date FROM portfolio_risk_snapshot"
    ),
    "plans": "SELECT DISTINCT plan_date AS day FROM trade_plan",
    "drafts": (
        "SELECT DISTINCT p.plan_date AS day FROM order_draft d "
        "JOIN trade_plan p ON p.plan_id = d.plan_id"
    ),
    "journal": "SELECT DISTINCT journal_date AS day FROM journal_entry",
}


@dataclass(frozen=True)
class PortfolioView:
    positions: list[dict]
    cash: list[dict]
    risk: list[dict]


class DashboardQueries:
    def __init__(self, db: DuckDBPyConnection) -> None:
        self._db = db

    def _rows(self, query: str, parameters: list | None = None) -> list[dict]:
        result = self._db.execute(query, parameters or [])
        names = [column[0] for column in result.description]
        return [dict(zip(names, row, strict=True)) for row in result.fetchall()]

    def dates(self, page: str) -> list[date]:
        return [
            row[0]
            for row in self._db.execute(
                f"SELECT day FROM ({_DATES[page]}) WHERE day IS NOT NULL ORDER BY day DESC"
            ).fetchall()
        ]

    def portfolio_dates(self) -> list[date]:
        return self.dates("portfolio")

    def brief(self, day: date):
        return BriefService(self._db).get_daily_brief(day)

    def benchmark_prices(self, day: date) -> list[dict]:
        return self._rows(
            """
            SELECT trade_date, symbol, close FROM daily_price
            WHERE trade_date <= ? AND symbol IN ('SPY', 'QQQ', 'VOO') AND close > 0
            QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY trade_date DESC) <= 45
            ORDER BY trade_date, symbol
            """,
            [day],
        )

    def accounts(self) -> list[dict]:
        return self._rows(
            "SELECT account_id, broker, account_role, individual_stock_policy, "
            "base_currency, is_active, order_draft_enabled, csv_import_enabled "
            "FROM portfolio_account ORDER BY account_id"
        )

    def portfolio(self, day: date, account_id: str | None) -> PortfolioView:
        parameters = [day, account_id, account_id]
        positions = self._rows(
            """
            SELECT account_id, symbol, quantity, market_price, market_value,
                cost_basis, unrealized_pnl, observed_at, source
            FROM portfolio_position_snapshot
            WHERE snapshot_date = ? AND (? IS NULL OR account_id = ?)
            QUALIFY row_number() OVER (
                PARTITION BY account_id, symbol ORDER BY observed_at DESC NULLS LAST,
                    created_at DESC NULLS LAST, snapshot_id DESC
            ) = 1
            ORDER BY market_value DESC NULLS LAST, account_id, symbol
            """,
            parameters,
        )
        cash = self._rows(
            """
            SELECT account_id, currency, cash_balance, available_to_trade, observed_at, source
            FROM portfolio_cash_snapshot
            WHERE snapshot_date = ? AND (? IS NULL OR account_id = ?)
            QUALIFY row_number() OVER (PARTITION BY account_id, currency
                ORDER BY observed_at DESC, created_at DESC NULLS LAST, snapshot_id DESC) = 1
            ORDER BY account_id, currency
            """,
            parameters,
        )
        risk = self._rows(
            """
            SELECT account_id, total_market_value, equity_value, cash_value,
                portfolio_risk_score, notes, created_at
            FROM portfolio_risk_snapshot
            WHERE snapshot_date = ? AND (? IS NULL OR account_id = ?)
            QUALIFY row_number() OVER (PARTITION BY account_id
                ORDER BY created_at DESC NULLS LAST, snapshot_id DESC) = 1
            ORDER BY account_id NULLS FIRST
            """,
            parameters,
        )
        return PortfolioView(positions, cash, risk)

    def plans(
        self, day: date, account_id: str | None, *, history: bool = False
    ) -> list[dict]:
        return self._rows(
            """
            SELECT plan_id, account_id, symbol, action, status, strategy_type, confidence, reason,
                supersedes_plan_id, plan_date
            FROM trade_plan p
            WHERE plan_date = ? AND (? IS NULL OR account_id = ?)
                AND (? OR NOT EXISTS (
                    SELECT 1 FROM trade_plan newer WHERE newer.supersedes_plan_id = p.plan_id
                ))
            ORDER BY account_id, symbol, created_at DESC NULLS LAST, plan_id
            """,
            [day, account_id, account_id, history],
        )

    def plan(self, plan_id: str):
        return get_trade_plan(self._db, plan_id)

    def drafts(
        self, day: date | None, account_id: str | None, status: OrderDraftStatus | None
    ) -> list[dict]:
        return self._rows(
            """
            SELECT d.draft_id, d.plan_id, d.account_id, d.symbol, d.instruction, d.order_type,
                d.quantity, d.limit_price, d.status, p.plan_date, d.created_at
            FROM order_draft d JOIN trade_plan p ON p.plan_id = d.plan_id
            WHERE (? IS NULL OR p.plan_date = ?::DATE) AND (? IS NULL OR d.account_id = ?)
                AND (? IS NULL OR d.status = ?)
            ORDER BY p.plan_date DESC, d.created_at DESC NULLS LAST, d.draft_id
            """,
            [day, day, account_id, account_id, status, status],
        )

    def draft(self, draft_id: str, config_dir):
        return OrderDraftService(self._db, config_dir=config_dir).get_draft(draft_id)

    def approval_history(self, draft_id: str) -> list[dict]:
        return self._rows(
            """
            SELECT decision, decision_note, decided_at, approval_id FROM approval_record
            WHERE draft_id = ? ORDER BY decided_at DESC, approval_id DESC
            """,
            [draft_id],
        )

    def journal(self, day: date, account_id: str | None) -> list[dict]:
        return self._rows(
            """
            SELECT journal_id, account_id, symbol, entry_type, action, decision_reason,
                user_note, system_note, created_at, draft_id, transaction_id
            FROM journal_entry
            WHERE journal_date = ? AND (? IS NULL OR account_id = ?)
            ORDER BY created_at DESC NULLS LAST, journal_id
            """,
            [day, account_id, account_id],
        )

    def performance(self, account_id: str | None) -> list[dict]:
        return self._rows(
            """
            SELECT review_id, account_id, review_type, strategy_type, period_start, period_end,
                trade_count, plan_count, approved_count, rejected_count, win_rate, average_return,
                max_drawdown, summary, lessons, next_actions
            FROM performance_review WHERE (? IS NULL OR account_id = ?)
            ORDER BY period_end DESC, review_date DESC, review_id DESC
            LIMIT 100
            """,
            [account_id, account_id],
        )

    def outcomes(self, account_id: str | None) -> list[dict]:
        return self._rows(
            """
            SELECT symbol, account_id, reference_date,
                CASE WHEN transaction_id IS NOT NULL THEN '成交' ELSE '计划' END AS basis,
                outcome_return_5d, outcome_return_20d, outcome_return_60d, outcome_label, lesson
            FROM trade_outcome WHERE (? IS NULL OR account_id = ?)
            ORDER BY reference_date DESC, outcome_id DESC LIMIT 200
            """,
            [account_id, account_id],
        )
