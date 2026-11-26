from enum import StrEnum

from duckdb import DuckDBPyConnection

from shared.models import DailyIndicator, DailySignal

from ..signals.evidence import RuleDetail


def save_analysis(
    db: DuckDBPyConnection,
    indicator: DailyIndicator,
    signal: DailySignal,
    details: tuple[RuleDetail, ...],
) -> DailySignal:
    indicator_fields = indicator.model_dump(exclude={"created_at"})
    signal_fields = signal.model_dump(exclude={"created_at"})
    columns = ", ".join(indicator_fields)
    placeholder = ", ".join("?" for _ in indicator_fields)
    updates = ", ".join(
        f"{name} = excluded.{name}"
        for name in indicator_fields
        if name not in ("symbol", "trade_date")
    )

    db.begin()
    try:
        db.execute(
            f"INSERT INTO daily_indicator ({columns}) VALUES ({placeholder}) "
            f"ON CONFLICT (symbol, trade_date) DO UPDATE SET {updates}",
            list(indicator_fields.values()),
        )
        db.execute(
            f"INSERT INTO daily_signal ({', '.join(signal_fields)}) "
            f"VALUES ({', '.join('?' for _ in signal_fields)}) "
            "ON CONFLICT (signal_id) DO NOTHING",
            [
                value.value if isinstance(value, StrEnum) else value
                for value in signal_fields.values()
            ],
        )
        db.executemany(
            """
            INSERT INTO signal_detail (
                detail_id, signal_id, component, rule_name, rule_value, score, explanation
            ) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (detail_id) DO NOTHING
            """,
            [
                (
                    f"{signal.signal_id}:{detail.component}:{detail.rule_name}",
                    signal.signal_id,
                    detail.component.value,
                    detail.rule_name,
                    detail.rule_value,
                    detail.score,
                    detail.explanation,
                )
                for detail in details
            ],
        )
        (created_at,) = db.execute(
            "SELECT created_at FROM daily_signal WHERE signal_id = ?",
            [signal.signal_id],
        ).fetchone()
        saved = DailySignal.model_validate({**signal_fields, "created_at": created_at})
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return saved
