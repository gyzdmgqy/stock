from pathlib import Path

WORKSPACE_DIRECTORIES = (
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


def create_workspace_directories(root: Path) -> None:
    for directory in WORKSPACE_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    create_workspace_directories(Path(__file__).resolve().parents[1])
