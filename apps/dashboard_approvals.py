from datetime import datetime
from pathlib import Path

import yaml
from duckdb import DuckDBPyConnection

from broker_gateway.drafts import DraftError, OrderDraftService, ReviewResult
from shared.db.database import DEFAULT_CONFIG_DIR
from shared.enums import ApprovalDecision as Decision
from shared.enums import ErrorType, OrderDraftStatus
from shared.models import OrderDraft

_DECISIONS = (Decision.APPROVED, Decision.REJECTED, Decision.DEFERRED)


def read_config(directory: Path, name: str) -> dict:
    config = yaml.safe_load((directory / f"{name}.yaml").read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("配置文件应为键值映射。")
    return config


class DashboardApprovalService:
    def __init__(
        self, db: DuckDBPyConnection, *, config_dir: Path = DEFAULT_CONFIG_DIR
    ) -> None:
        self._config = config_dir
        self._db = db
        self._gateway = OrderDraftService(db, config_dir=config_dir)

    def decide(
        self,
        reviewed: OrderDraft,
        decision: Decision,
        *,
        note: str | None = None,
        as_of: datetime | None = None,
    ) -> ReviewResult:
        if decision not in _DECISIONS:
            raise DraftError(
                ErrorType.VALIDATION_ERROR, "该决策不在本地仪表盘的审阅范围内。"
            )
        decision = Decision(decision)
        if decision is Decision.APPROVED:
            self._require_policy(reviewed)
        return self._gateway.record_decision(
            reviewed.draft_id,
            decision,
            reviewed_payload=(
                reviewed.order_snapshot() if decision is Decision.APPROVED else None
            ),
            decision_note=note.strip() or None if note else None,
            expected_draft=reviewed,
            as_of=as_of,
        )

    def reopen(
        self, reviewed: OrderDraft, *, as_of: datetime | None = None
    ) -> OrderDraft:
        if reviewed.status is not OrderDraftStatus.DEFERRED:
            raise DraftError(ErrorType.VALIDATION_ERROR, "仅已延期的草稿可以重新待审。")
        self._require_policy(reviewed)
        return self._gateway.reopen_deferred(
            reviewed.draft_id, expected_draft=reviewed, as_of=as_of
        )

    def _require_policy(self, draft: OrderDraft) -> None:
        accounts = read_config(self._config, "accounts")["accounts"]
        brokers = read_config(self._config, "broker")["brokers"]
        account = accounts.get(draft.account_id, {})
        broker = brokers.get(draft.broker.value.lower(), {})
        policy = self._db.execute(
            "SELECT broker, account_role, individual_stock_policy FROM portfolio_account "
            "WHERE account_id = ?",
            [draft.account_id],
        ).fetchone()
        if not (
            account.get("broker") == draft.broker
            and policy
            == (
                account.get("broker"),
                account.get("account_role"),
                account.get("individual_stock_policy"),
            )
            and account.get("is_active", True) is True
            and account.get("order_draft_enabled") is True
            and broker.get("enabled") is True
            and broker.get("order_draft_enabled") is True
        ):
            raise DraftError(
                ErrorType.RISK_RULE_BLOCKED, "账户或券商配置未允许批准此草稿。"
            )
