from pathlib import Path

import duckdb
from duckdb import DuckDBPyConnection

from .migrate import apply_migrations, read_migrations
from .seeds import seed_defaults

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "data/db/personal_cio.duckdb"
DEFAULT_CONFIG_DIR = ROOT / "config"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def connect_database(
    path: str | Path, *, read_only: bool = False
) -> DuckDBPyConnection:
    db = duckdb.connect(str(path), read_only=read_only)
    try:
        db.execute("SET TimeZone = 'UTC'")
    except duckdb.Error:
        db.close()
        raise
    return db


def initialize_database(
    path: str | Path = DEFAULT_DB_PATH,
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> int:
    migrations = read_migrations(migrations_dir)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(path) as db:
        db.begin()
        try:
            version = apply_migrations(db, migrations)
            seed_defaults(db, config_dir)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return version
