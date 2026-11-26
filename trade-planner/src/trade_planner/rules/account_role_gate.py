from shared.enums import AccountRole, Broker, IndividualStockPolicy

from ..planners.base import AccountPolicy, AssetType


def is_exit_only_stock(account: AccountPolicy, asset_type: AssetType | None) -> bool:
    return asset_type == "STOCK" and (
        account.broker is Broker.VANGUARD
        or account.account_role is AccountRole.CORE_PASSIVE
        or account.individual_stock_policy is IndividualStockPolicy.EXIT_ONLY
    )


def supports_active_trading(
    account: AccountPolicy, asset_type: AssetType | None
) -> bool:
    return (
        account.is_active
        and account.broker is Broker.SCHWAB
        and account.account_role is AccountRole.ACTIVE_TRADING
        and account.individual_stock_policy is IndividualStockPolicy.ACTIVE_ALLOWED
        and asset_type in ("STOCK", "ETF")
    )
