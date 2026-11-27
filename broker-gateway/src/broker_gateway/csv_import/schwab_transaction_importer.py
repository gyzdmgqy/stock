from ..adapters.schwab.csv_format import TRANSACTIONS, TYPES
from .base_importer import TransactionNormalizer
from .normalizer import Account

__all__ = ["TRANSACTIONS", "transaction_importer"]


def transaction_importer(account: Account, source_file: str) -> TransactionNormalizer:
    return TransactionNormalizer(account, source_file, TYPES)
