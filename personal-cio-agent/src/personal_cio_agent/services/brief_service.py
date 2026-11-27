import json
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from duckdb import DuckDBPyConnection

from shared.db.database import ROOT
from shared.models import DailyCioBrief

from ..brief_generator.daily_brief import (
    brief_id_for,
    build_daily_brief,
    render_markdown,
)
from ._brief_sources import (
    journal_reminders,
    market_summary,
    portfolio_and_risk,
    trade_plans_and_drafts,
)

DEFAULT_OUTPUT_DIR = ROOT / "outputs/briefs"
_JSON_FIELDS = {
    "market_summary",
    "portfolio_summary",
    "risk_summary",
    "trade_plan_summary",
    "order_draft_summary",
    "journal_reminders",
}
_COLUMNS = tuple(DailyCioBrief.model_fields)


class BriefService:
    def __init__(
        self, db: DuckDBPyConnection, *, output_dir: str | Path = DEFAULT_OUTPUT_DIR
    ) -> None:
        self._db = db
        self._output_dir = Path(output_dir).resolve()

    def generate_daily_brief(
        self,
        brief_date: date,
        *,
        as_of: datetime | None = None,
        signal_ids: tuple[str, ...] | None = None,
        plan_ids: tuple[str, ...] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> DailyCioBrief:
        if type(brief_date) is not date:
            raise TypeError("简报日期必须为 date")
        markdown = self._output_dir / f"{brief_date.isoformat()}_Daily_CIO_Brief.md"
        payload = markdown.with_suffix(".json")
        staged: list[tuple[Path, Path]] = []
        try:
            self._db.begin()
            try:
                portfolio, risk = portfolio_and_risk(self._db, brief_date, as_of)
                risk.key_risks = list(dict.fromkeys([*risk.key_risks, *warnings]))
                plans, drafts = trade_plans_and_drafts(self._db, brief_date, plan_ids)
                brief = build_daily_brief(
                    brief_date,
                    market=market_summary(self._db, brief_date, signal_ids),
                    portfolio=portfolio,
                    risk=risk,
                    plans=plans,
                    drafts=drafts,
                    reminders=journal_reminders(self._db, brief_date),
                )
                brief.markdown_path = str(markdown)
                brief = self._save(brief)
                self._output_dir.mkdir(parents=True, exist_ok=True)
                for destination, content in (
                    (markdown, render_markdown(brief)),
                    (payload, brief.model_dump_json(indent=2) + "\n"),
                ):
                    staged.append((_stage_file(destination, content), destination))
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

            # 数据库是主记录。每个文件单独原子替换，重跑可恢复导出。
            for temporary, destination in staged:
                temporary.replace(destination)
            return brief
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)

    def get_daily_brief(self, brief_date: date) -> DailyCioBrief | None:
        row = self._db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM daily_cio_brief WHERE brief_id = ?",
            [brief_id_for(brief_date)],
        ).fetchone()
        if row is None:
            return None
        fields = dict(zip(_COLUMNS, row, strict=True))
        for field in _JSON_FIELDS:
            if fields[field] is not None:
                fields[field] = json.loads(fields[field])
        return DailyCioBrief.model_validate(fields)

    def _save(self, brief: DailyCioBrief) -> DailyCioBrief:
        fields = brief.model_dump(mode="json", exclude={"created_at"})
        updates = ", ".join(
            f"{field} = excluded.{field}" for field in fields if field != "brief_id"
        )
        values = [
            (
                json.dumps(value, ensure_ascii=False, allow_nan=False)
                if field in _JSON_FIELDS and value is not None
                else value
            )
            for field, value in fields.items()
        ]
        (created_at,) = self._db.execute(
            f"INSERT INTO daily_cio_brief ({', '.join(fields)}) "
            f"VALUES ({', '.join('?' for _ in fields)}) "
            f"ON CONFLICT (brief_id) DO UPDATE SET {updates} RETURNING created_at",
            values,
        ).fetchone()
        brief.created_at = created_at
        return brief


def _stage_file(destination: Path, content: str) -> Path:
    staged = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            staged = Path(stream.name)
            stream.write(content)
        return staged
    except BaseException:
        if staged is not None:
            staged.unlink(missing_ok=True)
        raise
