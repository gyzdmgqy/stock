import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hmac import compare_digest
from pathlib import Path

from duckdb import DuckDBPyConnection
from duckdb import Error as DuckDBError
from pydantic import BaseModel, ValidationError

from investment_journal.services.journal_service import JournalService
from shared.db.database import ROOT
from shared.enums import AccountRole, Broker, ErrorType
from shared.models import BrokerTransaction, PortfolioCashSnapshot, PortfolioSnapshot

from ..adapters.csv_format import label
from . import (
    schwab_position_importer,
    schwab_transaction_importer,
    vanguard_position_importer,
    vanguard_transaction_importer,
)
from .base_importer import EXECUTIONS, read_rows, transaction_facts
from .cash_importer import normalize_cash
from .normalizer import Account, digest
from .validators import CsvImportError, optional, validation

_IMPORTERS = {
    Broker.SCHWAB: (schwab_transaction_importer, schwab_position_importer),
    Broker.VANGUARD: (vanguard_transaction_importer, vanguard_position_importer),
}
_POSITION_FIELDS = tuple(
    name
    for name in PortfolioSnapshot.model_fields
    if name not in {"broker", "account_role"}
)
_TRANSACTION_FIELDS = tuple(BrokerTransaction.model_fields)


@dataclass(frozen=True)
class ImportPreview:
    path: Path
    file_digest: str
    broker: Broker
    account_id: str
    transactions: tuple[BrokerTransaction, ...]
    positions: tuple[PortfolioSnapshot, ...]
    cash: tuple[PortfolioCashSnapshot, ...]
    duplicate_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    confirmation_token: str = ""

    def review_payload(self) -> dict:
        return {
            "broker": self.broker.value,
            "account_id": self.account_id,
            "file_sha256": self.file_digest,
            "transactions": [
                record.model_dump(mode="json") for record in self.transactions
            ],
            "positions": [record.model_dump(mode="json") for record in self.positions],
            "cash": [record.model_dump(mode="json") for record in self.cash],
            "duplicate_ids": self.duplicate_ids,
            "warnings": self.warnings,
        }

    def _token(self) -> str:
        return digest((str(self.path), self.review_payload()))


@dataclass(frozen=True)
class ImportResult:
    transactions_inserted: int
    positions_inserted: int
    cash_inserted: int
    journal_entries_created: int
    duplicates_skipped: int
    archive_path: Path


class CsvImportService:
    def __init__(
        self,
        db: DuckDBPyConnection,
        *,
        raw_dir: Path = ROOT / "imports/raw",
        archive_dir: Path = ROOT / "imports/archive",
    ) -> None:
        self._db = db
        self._raw = raw_dir.resolve()
        self._archive = archive_dir.resolve()
        if self._raw.is_relative_to(self._archive) or self._archive.is_relative_to(
            self._raw
        ):
            raise ValueError("原始文件和归档目录必须分开。")

    def preview(
        self,
        path: str | Path,
        *,
        broker: Broker,
        account_id: str,
        observed_at: datetime | None = None,
        source_account: str | None = None,
    ) -> ImportPreview:
        try:
            broker = Broker(broker)
        except ValueError as exc:
            raise validation("券商不受支持。") from exc
        account = self._account(broker, account_id)
        if observed_at is not None and (
            not isinstance(observed_at, datetime) or observed_at.utcoffset() is None
        ):
            raise validation("快照观察时间必须包含时区。")
        path, data = self._read(path)
        checksum = hashlib.sha256(data).hexdigest()
        trans_adapter, pos_adapter = _IMPORTERS[broker]
        trans = trans_adapter.transaction_importer(account, f"sha256:{checksum}")
        transactions: dict[str, BrokerTransaction] = {}
        positions: dict[str, PortfolioSnapshot] = {}
        cash: list[PortfolioCashSnapshot] = []
        sources: set[str] = set()
        ended: set[str] = set()
        source_unverified = False
        repeated = 0
        for section, row, fields in read_rows(
            data, trans_adapter.TRANSACTIONS, pos_adapter.POSITIONS
        ):
            ticker = label(fields.get("symbol", ""))
            is_total = (
                section == "positions" and ticker in pos_adapter.TOTAL_ROWS
            ) or (
                section == "transactions"
                and label(fields.get("trade_date", "")) == "transactions total"
            )
            if section in ended:
                raise validation("汇总行后还有同类数据，无法确定账户边界。", row)
            if is_total:
                ended.add(section)
                continue
            external_id = optional(fields.get("source_account", ""))
            if "source_account" in fields and external_id is None:
                raise validation("CSV 账户列为空。", row)
            if external_id:
                sources.add(external_id)
                if len(sources) > 1:
                    raise validation("文件包含多个账户，请按账户拆分。", row)
            else:
                source_unverified = True
            currency = optional(fields.get("currency", ""))
            if (section == "cash" and currency is None) or (
                currency and currency.upper() != "USD"
            ):
                raise validation("首版只支持 USD，独立现金记录必须明确填写币种。", row)

            if section == "transactions":
                transaction = trans.normalize(fields, row)
                previous = transactions.get(transaction.transaction_id)
                if previous is not None:
                    if transaction_facts(previous) != transaction_facts(transaction):
                        raise validation(
                            "文件内同一券商成交 ID 对应的交易事实冲突。", row
                        )
                    repeated += 1
                else:
                    transactions[transaction.transaction_id] = transaction
                continue

            if observed_at is None:
                raise validation("导入持仓或现金时，必须提供带时区的观察时间。", row)
            try:
                if section == "cash" or ticker in pos_adapter.CASH_ROWS:
                    if cash:
                        raise validation(
                            "同一导入只能提供一条现金快照，请先合并现金字段。", row
                        )
                    if section == "positions":
                        fields = {"cash_balance": fields["market_value"]}
                    cash.append(normalize_cash(fields, row, account, observed_at))
                else:
                    position = pos_adapter.normalize_position(
                        fields, row, account, observed_at
                    )
                    if position.symbol in positions:
                        raise validation(
                            "同一标的出现多行，请导出账户汇总持仓而非批次明细。", row
                        )
                    positions[position.symbol] = position
            except ValidationError as exc:
                raise validation("快照字段超出有效范围或精度。", row) from exc

        if source_account is not None and (
            sources != {source_account.strip()} or source_unverified
        ):
            raise validation("文件账户与指定的券商账户不一致或无法验证。")
        if not (transactions or positions or cash):
            raise validation("CSV 没有可导入的记录。")

        warnings = []
        if source_account is None:
            warnings.append("请核对本地账户与导出文件的归属；没有自动验证券商账号。")
        if any(not item.broker_transaction_id for item in transactions.values()):
            warnings.append(
                "部分交易无券商成交 ID；按字段和出现次数去重，跨文件的相同成交仍需人工核对。"
            )
        if repeated:
            warnings.append(f"已合并文件内 {repeated} 条完全相同且成交 ID 相同的记录。")
        if any(item.transaction_type == "OTHER" for item in transactions.values()):
            warnings.append("存在 OTHER 类型记录，请核对未识别的交易类型。")
        if positions:
            warnings.append("未出现在文件中的持仓不会被记为零。")
        draft = ImportPreview(
            path,
            checksum,
            broker,
            account.account_id,
            tuple(transactions.values()),
            tuple(positions.values()),
            tuple(cash),
            (),
            tuple(warnings),
        )
        draft = replace(draft, duplicate_ids=self._duplicates(draft))
        return replace(draft, confirmation_token=draft._token())

    def commit(
        self, preview: ImportPreview, *, confirmation_token: str
    ) -> ImportResult:
        if not isinstance(confirmation_token, str) or not compare_digest(
            preview.confirmation_token.encode("utf-8"),
            confirmation_token.encode("utf-8"),
        ):
            raise CsvImportError(
                ErrorType.USER_APPROVAL_REQUIRED, "请先确认本次导入预览。"
            )
        if preview._token() != preview.confirmation_token:
            raise validation("预览内容已变更，请重新预览。")
        path, data = self._read(preview.path)
        if hashlib.sha256(data).hexdigest() != preview.file_digest:
            raise validation("CSV 内容已变更，请重新预览。")

        destination = self._archive_target(preview)
        self._destination_is_new(destination, data)
        self._db.begin()
        try:
            self._account(preview.broker, preview.account_id)
            duplicate_ids = self._duplicates(preview)
            if duplicate_ids != preview.duplicate_ids:
                raise validation("已入库记录在预览后发生变更，请重新预览。")
            existing = set(duplicate_ids)
            transactions = [
                r for r in preview.transactions if r.transaction_id not in existing
            ]
            positions = [r for r in preview.positions if r.snapshot_id not in existing]
            cash = [r for r in preview.cash if r.snapshot_id not in existing]
            journals = 0
            journal = JournalService(self._db)
            for record in transactions:
                self._insert("broker_transaction", record, _TRANSACTION_FIELDS)
                if record.transaction_type in EXECUTIONS:
                    journal.record_transaction(record, in_transaction=True)
                    journals += 1
            for record in positions:
                self._insert("portfolio_position_snapshot", record, _POSITION_FIELDS)
            for record in cash:
                self._insert(
                    "portfolio_cash_snapshot",
                    record,
                    tuple(PortfolioCashSnapshot.model_fields),
                )
            self._db.commit()
        except BaseException as exc:
            self._db.rollback()
            if isinstance(exc, CsvImportError):
                raise
            if isinstance(exc, (DuckDBError, ValueError)):
                raise CsvImportError(
                    ErrorType.VALIDATION_ERROR, "导入写入失败，数据库已回滚。"
                ) from exc
            raise

        try:
            if path.is_symlink() or path.read_bytes() != data:
                raise OSError("CSV changed")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if self._destination_is_new(destination, data):
                path.rename(destination)
            else:
                path.unlink()
        except (OSError, CsvImportError) as exc:
            raise CsvImportError(
                ErrorType.UNKNOWN,
                "数据库已提交，但归档未完成。原文件保留时，可重新预览并确认，已有记录会去重。",
                committed=True,
            ) from exc

        return ImportResult(
            len(transactions),
            len(positions),
            len(cash),
            journals,
            len(existing),
            destination,
        )

    def _read(self, path: str | Path) -> tuple[Path, bytes]:
        path = Path(path)
        try:
            if path.is_symlink():
                raise validation("不能导入符号链接。")
            path = path.resolve()
            if path.suffix.lower() != ".csv" or not path.is_relative_to(self._raw):
                raise validation("只接受原始导入目录下的 CSV 文件。")
            if not path.is_file():
                raise OSError("not a file")
            return path, path.read_bytes()
        except OSError as exc:
            raise CsvImportError(ErrorType.DATA_MISSING, "无法读取原始 CSV。") from exc

    def _account(self, broker: Broker, account_id: str) -> Account:
        if broker not in _IMPORTERS:
            raise validation("首版仅支持 Schwab 或 Vanguard。")
        row = self._db.execute(
            "SELECT broker, account_role, is_active, csv_import_enabled, base_currency "
            "FROM portfolio_account WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None or row[0] != broker:
            raise validation("本地账户不存在，或配置的券商与导入券商不一致。")
        if not row[2] or not row[3] or row[4] != "USD":
            raise validation("本地账户必须启用 USD 和 CSV 导入。")
        try:
            return Account(account_id, broker, AccountRole(row[1]))
        except ValueError as exc:
            raise validation("本地账户角色无效。") from exc

    def _archive_target(self, preview: ImportPreview) -> Path:
        target = (
            self._archive
            / preview.broker.value.lower()
            / digest(preview.account_id)[:16]
            / f"{preview.file_digest}.csv"
        )
        if target.is_symlink() or target.resolve() != target:
            raise validation("归档路径不能通过符号链接。")
        return target

    @staticmethod
    def _destination_is_new(path: Path, data: bytes) -> bool:
        try:
            if not path.exists() and not path.is_symlink():
                return True
            if path.is_symlink() or path.read_bytes() != data:
                raise validation("归档路径已存在且内容不一致，原文件未移动。")
            return False
        except OSError as exc:
            raise validation("无法核对归档文件。") from exc

    def _duplicates(self, preview: ImportPreview) -> tuple[str, ...]:
        duplicates = []
        if preview.transactions:
            columns = ", ".join(_TRANSACTION_FIELDS)
            rows = self._db.execute(
                f"SELECT {columns} FROM broker_transaction WHERE broker = ? AND account_id = ? "
                "AND deduplication_key IN (SELECT unnest(?))",
                [
                    preview.broker.value,
                    preview.account_id,
                    [r.deduplication_key for r in preview.transactions],
                ],
            ).fetchall()
            candidates = {r.deduplication_key: r for r in preview.transactions}
            for row in rows:
                stored = BrokerTransaction.model_validate(
                    dict(zip(_TRANSACTION_FIELDS, row, strict=True))
                )
                candidate = candidates[stored.deduplication_key]
                if transaction_facts(stored) != transaction_facts(candidate):
                    raise validation("同一券商成交 ID 对应的已导入交易事实冲突。")
                duplicates.append(candidate.transaction_id)
        for table, records in (
            ("portfolio_position_snapshot", preview.positions),
            ("portfolio_cash_snapshot", preview.cash),
        ):
            if records:
                rows = self._db.execute(
                    f"SELECT snapshot_id FROM {table} WHERE snapshot_id IN (SELECT unnest(?))",
                    [[r.snapshot_id for r in records]],
                ).fetchall()
                duplicates.extend(row[0] for row in rows)
        return tuple(sorted(duplicates))

    def _insert(self, table: str, record: BaseModel, fields: tuple[str, ...]) -> None:
        fields = tuple(field for field in fields if field != "created_at")
        values = [getattr(record, field) for field in fields]
        self._db.execute(
            f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            [value.value if isinstance(value, StrEnum) else value for value in values],
        )
