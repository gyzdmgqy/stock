from datetime import UTC, date, datetime

from apps.dashboard_queries import DashboardQueries
from shared.db import connect_database, initialize_database


def test_portfolio_uses_selected_day_without_inventing_cash_or_shares(tmp_path):
    path = tmp_path / "snapshot.duckdb"
    initialize_database(path)
    today, previous = date(2026, 6, 8), date(2026, 6, 5)
    with connect_database(path) as db:
        for index, day, hour, quantity in (
            (1, previous, 20, 4),
            (2, today, 16, 3),
            (3, today, 18, 0),
        ):
            db.execute(
                "INSERT INTO portfolio_position_snapshot (snapshot_id, account_id, snapshot_date, observed_at, "
                "symbol, quantity, market_value) VALUES (?, 'SCHWAB_ROTH', ?, ?, 'VRTX', ?, ?)",
                [
                    str(index),
                    day,
                    datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                    quantity,
                    100 * quantity,
                ],
            )
        db.execute(
            "INSERT INTO portfolio_cash_snapshot (snapshot_id, account_id, snapshot_date, observed_at, currency, "
            "cash_balance, source) VALUES ('c', 'SCHWAB_ROTH', ?, ?, 'USD', 0, 'CSV')",
            [today, datetime(2026, 6, 8, 18, tzinfo=UTC)],
        )
        queries = DashboardQueries(db)
        assert queries.portfolio_dates() == [today, previous]
        view = queries.portfolio(today, "SCHWAB_ROTH")
        assert [(row["symbol"], row["quantity"]) for row in view.positions] == [
            ("VRTX", 0)
        ]
        assert len(view.cash) == 1 and view.cash[0]["cash_balance"] == 0
        assert view.cash[0]["available_to_trade"] is None
        assert not view.risk
        assert not queries.portfolio(today, "VANGUARD_ROTH").positions
        assert queries.portfolio(previous, "SCHWAB_ROTH").positions[0]["quantity"] == 4
