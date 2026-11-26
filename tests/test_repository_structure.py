from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    "market-data-service",
    "analysis-engine",
    "trade-planner",
    "broker-gateway",
    "personal-cio-agent",
    "investment-journal",
)
CONFIG_SECTIONS = {
    "app.yaml": "app",
    "accounts.yaml": "accounts",
    "symbols.yaml": "core_index",
    "risk.yaml": "risk",
    "broker.yaml": "brokers",
}
RUNTIME_DIRECTORIES = (
    "data/db",
    "data/market",
    "data/signals",
    "data/reports",
    "data/journal",
    "imports/raw/schwab",
    "imports/raw/vanguard",
    "imports/normalized",
    "imports/archive",
    "outputs/briefs",
    "outputs/trade_plans",
    "outputs/order_drafts",
    "outputs/journal",
    "logs",
    "backup/daily",
    "backup/weekly",
)


def test_repository_structure():
    directories = {"docs", "config", "scripts", "tests"}
    directories.update(
        f"{name}/{part}" for name in SERVICES for part in ("src", "tests", "config")
    )
    directories.update(
        f"shared/{part}"
        for part in ("models", "enums", "schemas", "utils", "constants")
    )
    directories.update(
        f"tests/{part}" for part in ("unit", "integration", "regression")
    )
    files = {"requirements.txt", "pyproject.toml", ".gitignore", "README.md"}
    files.update(
        f"{name}/{file}"
        for name in SERVICES
        for file in ("README.md", "pyproject.toml")
    )

    missing = sorted(
        {name for name in directories if not (ROOT / name).is_dir()}
        | {name for name in files if not (ROOT / name).is_file()}
    )
    assert not missing, f"缺少仓库文件或目录：{', '.join(missing)}"


@pytest.mark.parametrize(("filename", "section"), CONFIG_SECTIONS.items())
def test_sample_config_loads(filename, section):
    import yaml

    config = yaml.safe_load((ROOT / "config" / filename).read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    assert config[section]


def test_sample_settings_keep_local_defaults():
    import yaml

    def read_config(filename):
        return yaml.safe_load((ROOT / "config" / filename).read_text(encoding="utf-8"))

    assert read_config("app.yaml")["app"]["timezone"] == "America/Chicago"
    assert all(
        broker["order_submission_enabled"] is False
        for broker in read_config("broker.yaml")["brokers"].values()
    )
    assert all(
        account["api_sync_enabled"] is False
        for account in read_config("accounts.yaml")["accounts"].values()
    )


def test_workspace_setup_on_fresh_checkout(tmp_path):
    from scripts.init_workspace import create_workspace_directories

    create_workspace_directories(tmp_path)

    assert all((tmp_path / name).is_dir() for name in RUNTIME_DIRECTORIES)
    assert not (tmp_path / ".env").exists()
    assert not list(tmp_path.rglob("*.duckdb"))
    journal = tmp_path / "data/journal/existing.txt"
    journal.write_text("existing", encoding="utf-8")

    create_workspace_directories(tmp_path)

    assert journal.read_text(encoding="utf-8") == "existing"
