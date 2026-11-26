from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from re import fullmatch

from duckdb import DuckDBPyConnection, Error


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sql: str

    @property
    def checksum(self) -> str:
        return sha256(self.sql.encode("utf-8")).hexdigest()


def read_migrations(directory: Path) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = fullmatch(r"(\d{4})_[a-z0-9_]+\.sql", path.name)
        if not match:
            raise MigrationError(f"迁移文件名无效：{path.name}")
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            raise MigrationError(f"迁移 SQL 为空：{path.name}")
        migrations.append(Migration(int(match[1]), path.name, sql))

    if not migrations or [item.version for item in migrations] != list(
        range(1, len(migrations) + 1)
    ):
        raise MigrationError("迁移版本必须从 0001 开始连续编号，且每个版本只能出现一次")
    return migrations


def apply_migrations(db: DuckDBPyConnection, migrations: list[Migration]) -> int:
    # 调用方在同一事务中执行迁移和种子写入。
    tables = {name for (name,) in db.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_catalog = current_database() AND table_schema = current_schema()
            """).fetchall()}
    if "_schema_migrations" not in tables:
        if tables:
            raise MigrationError("数据库已有对象但没有迁移记录，请先确认其来源")
        db.execute("""
            CREATE TABLE _schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)

    applied = db.execute(
        "SELECT version, filename, checksum FROM _schema_migrations ORDER BY version"
    ).fetchall()
    if len(applied) > len(migrations) or any(
        version != index for index, (version, _, _) in enumerate(applied, start=1)
    ):
        raise MigrationError("数据库迁移版本与本地迁移文件不兼容")
    if not applied and tables - {"_schema_migrations"}:
        raise MigrationError("数据库已有对象但没有已应用的迁移记录")

    for migration, (_, filename, checksum) in zip(migrations, applied):
        if filename != migration.filename or checksum != migration.checksum:
            raise MigrationError(f"已应用的迁移文件被修改：{filename}")

    for migration in migrations[len(applied) :]:
        try:
            db.execute(migration.sql)
            db.execute(
                "INSERT INTO _schema_migrations (version, filename, checksum) VALUES (?, ?, ?)",
                [migration.version, migration.filename, migration.checksum],
            )
        except Error as exc:
            raise MigrationError(f"无法应用迁移 {migration.filename}：{exc}") from exc

    return migrations[-1].version
