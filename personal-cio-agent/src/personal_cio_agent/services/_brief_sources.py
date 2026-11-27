from datetime import date, datetime
from decimal import Decimal
from math import isfinite

from duckdb import DuckDBPyConnection

from shared.enums import AccountRole
from shared.models.brief import (
    MarketSummary,
    OrderDraftSummary,
    PortfolioSummary,
    RiskSummary,
    TradePlanSummary,
)


def market_summary(
    db: DuckDBPyConnection, day: date, signal_ids: tuple[str, ...] | None = None
) -> MarketSummary:
    rows = db.execute(
        """
        SELECT symbol, market_regime, confidence, reason FROM daily_signal
        WHERE trade_date = ? AND symbol IN ('SPY', 'QQQ')
          AND (? OR signal_id IN (SELECT unnest(CAST(? AS VARCHAR[]))))
        QUALIFY row_number() OVER (
            PARTITION BY symbol ORDER BY created_at DESC NULLS LAST, signal_id DESC
        ) = 1
        ORDER BY symbol = 'SPY' DESC
        """,
        [day, signal_ids is None, list(signal_ids or ())],
    ).fetchall()
    signals = {
        symbol: (regime, confidence, reason)
        for symbol, regime, confidence, reason in rows
    }
    regime, confidence, _ = signals.get("SPY", (None, None, None))
    points = []
    if regime is None:
        points.append("缺少当日 SPY 行情状态。")
    for symbol, (state, _, reason) in signals.items():
        summary = reason.strip() if reason else ""
        points.append(f"{symbol} · {summary or state or '行情状态待补齐'}")
    return MarketSummary(market_regime=regime, confidence=confidence, key_points=points)


def portfolio_and_risk(
    db: DuckDBPyConnection, day: date, as_of: datetime | None = None
) -> tuple[PortfolioSummary, RiskSummary]:
    accounts = db.execute(
        "SELECT account_id, account_role, base_currency FROM portfolio_account "
        "WHERE is_active ORDER BY account_id"
    ).fetchall()
    recorded = db.execute(
        """
        SELECT account_id, TRY_CAST(total_market_value AS DECIMAL(20, 6)),
            portfolio_risk_score, notes
        FROM portfolio_risk_snapshot WHERE snapshot_date = ?
        AND (CAST(? AS TIMESTAMPTZ) IS NULL OR created_at <= ?)
        QUALIFY row_number() OVER (
            PARTITION BY account_id ORDER BY created_at DESC NULLS LAST, snapshot_id DESC
        ) = 1
        """,
        [day, as_of, as_of],
    ).fetchall()
    snapshots = {
        account: (value, score, notes) for account, value, score, notes in recorded
    }
    combined_value, combined_score, combined_notes = snapshots.get(
        None, (None, None, None)
    )
    risks = []

    def known_sum(group: list[str]) -> Decimal | None:
        values = [snapshots.get(account, (None, None, None))[0] for account in group]
        if values and all(value is not None for value in values):
            return sum(values, Decimal(0))
        return None

    usd_only = all(currency == "USD" for _, _, currency in accounts)
    total = combined_value if usd_only else None
    if total is None and usd_only:
        total = known_sum([account for account, _, _ in accounts])
    if total is None:
        risks.append("缺少完整的当日 USD 组合净值。")

    role_values = {}
    for role, label in (
        (AccountRole.CORE_PASSIVE, "核心账户"),
        (AccountRole.ACTIVE_TRADING, "主动交易账户"),
    ):
        group = [
            (account, currency)
            for account, actual, currency in accounts
            if actual == role
        ]
        role_values[role] = (
            known_sum([account for account, _ in group])
            if all(currency == "USD" for _, currency in group)
            else None
        )
        if group and role_values[role] is None:
            risks.append(f"缺少完整的当日 {label} USD 净值。")

    if combined_score is None or not isfinite(combined_score):
        risks.append("缺少当日组合风险评分。")
    else:
        risks.append(f"组合风险评分 {combined_score:g}，保留快照口径。")
    if combined_notes and combined_notes.strip():
        risks.append(combined_notes.strip())

    for account, _, _ in accounts:
        _, _, note = snapshots.get(account, (None, None, None))
        if note and note.strip():
            risks.append(f"{account} · {note.strip()}")

    return (
        PortfolioSummary(
            total_value=total,
            core_passive_value=role_values[AccountRole.CORE_PASSIVE],
            active_trading_value=role_values[AccountRole.ACTIVE_TRADING],
            key_positions=_positions(db, day, as_of),
        ),
        RiskSummary(key_risks=risks),
    )


def _positions(db: DuckDBPyConnection, day: date, as_of: datetime | None) -> list[dict]:
    rows = db.execute(
        """
        WITH latest AS (
            SELECT p.account_id, p.symbol, p.quantity,
                TRY_CAST(p.market_value AS DECIMAL(20, 6)) AS value
            FROM portfolio_position_snapshot AS p
            JOIN portfolio_account AS a ON p.account_id = a.account_id
            WHERE p.snapshot_date = ? AND a.is_active AND a.base_currency = 'USD'
            AND (CAST(? AS TIMESTAMPTZ) IS NULL OR p.observed_at <= ?)
            QUALIFY row_number() OVER (
                PARTITION BY p.account_id, p.symbol
                ORDER BY p.observed_at DESC NULLS LAST,
                    p.created_at DESC NULLS LAST, p.snapshot_id DESC
            ) = 1
        )
        SELECT account_id, symbol, value FROM latest WHERE quantity > 0
        ORDER BY value DESC NULLS LAST, account_id, symbol LIMIT 5
        """,
        [day, as_of, as_of],
    ).fetchall()
    return [
        {
            "account_id": account,
            "symbol": symbol,
            "market_value": str(value) if value is not None else None,
        }
        for account, symbol, value in rows
    ]


def trade_plans_and_drafts(
    db: DuckDBPyConnection, day: date, plan_ids: tuple[str, ...] | None = None
) -> tuple[list[TradePlanSummary], list[OrderDraftSummary]]:
    plans = [
        TradePlanSummary(
            plan_id=plan_id,
            symbol=symbol,
            action=action,
            confidence=confidence,
            account_id=account,
            status=status,
        )
        for plan_id, symbol, action, confidence, account, status in db.execute(
            """
            SELECT plan_id, symbol, action, confidence, account_id, status
            FROM trade_plan WHERE plan_date = ?
            AND (? OR plan_id IN (SELECT unnest(CAST(? AS VARCHAR[]))))
            QUALIFY row_number() OVER (
                PARTITION BY account_id, symbol
                ORDER BY created_at DESC NULLS LAST, plan_id DESC
            ) = 1
            ORDER BY account_id, symbol
            """,
            [day, plan_ids is None, list(plan_ids or ())],
        ).fetchall()
    ]
    if not plans:
        return plans, []
    drafts = [
        OrderDraftSummary(
            draft_id=draft_id,
            symbol=symbol,
            status=status,
            account_id=account,
            plan_id=plan_id,
        )
        for draft_id, symbol, status, account, plan_id in db.execute(
            """
            SELECT draft_id, symbol, status, account_id, plan_id FROM order_draft
            WHERE plan_id IN (SELECT unnest(?))
            ORDER BY account_id NULLS LAST, symbol, created_at NULLS LAST, draft_id
            """,
            [[plan.plan_id for plan in plans]],
        ).fetchall()
    ]
    return plans, drafts


def journal_reminders(db: DuckDBPyConnection, day: date) -> list[str]:
    rows = db.execute(
        """
        WITH notes AS (
            SELECT journal_id, journal_date, created_at, coalesce(symbol, account_id) AS subject,
                coalesce(nullif(trim(user_note), ''), nullif(trim(decision_reason), ''),
                    nullif(trim(system_note), '')) AS note
            FROM journal_entry
            WHERE journal_date < ? AND NOT starts_with(journal_id, 'JRN-BRIEF-')
        )
        SELECT journal_date, subject, note FROM notes WHERE note IS NOT NULL
        ORDER BY journal_date DESC, created_at DESC NULLS LAST, journal_id DESC LIMIT 5
        """,
        [day],
    ).fetchall()
    return [
        f"{journal_date} · {subject + ' · ' if subject else ''}{note}"
        for journal_date, subject, note in rows
    ]
