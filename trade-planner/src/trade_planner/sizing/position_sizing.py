from decimal import ROUND_DOWN, Decimal

from shared.models.trade_plan import PositionSize

from ..planners.base import EntryPrices, PortfolioState, RiskLimits


def size_entry(
    state: PortfolioState, prices: EntryPrices, limits: RiskLimits
) -> tuple[PositionSize | None, str | None]:
    if state.account_equity is None or state.account_equity <= 0:
        return None, "缺少有效的账户净值。"
    if state.position_value is None or state.available_cash is None:
        return None, "缺少持仓市值或可用现金。"
    if (
        state.combined_equity is None
        or state.combined_equity < state.account_equity
        or state.combined_symbol_value is None
        or state.combined_symbol_value < state.position_value
        or state.combined_sector_value is None
        or state.combined_sector_value < state.combined_symbol_value
    ):
        return None, "组合净值、单股或板块敞口缺失或不一致。"

    account_equity = state.account_equity
    limit = prices.limit_price
    risk_per_share = limit - prices.stop_price
    budget = min(
        account_equity * limits.max_new_trade_weight,
        account_equity * limits.max_single_stock_weight - state.position_value,
        state.available_cash,
        account_equity * limits.max_trade_risk_percent * limit / risk_per_share,
    )
    quantity = (budget / limit).to_integral_value(rounding=ROUND_DOWN)
    if quantity < 1:
        return None, "可用现金、账户仓位或单笔风险额度不足一股。"

    value = quantity * limit
    if (
        state.combined_symbol_value + value
        > state.combined_equity * limits.max_combined_symbol_weight
    ):
        return None, "拟议仓位会使组合单股敞口超过上限。"
    if (
        state.combined_sector_value + value
        > state.combined_equity * limits.max_combined_sector_weight
    ):
        return None, "拟议仓位会使组合板块敞口超过上限。"

    return position_size(state, quantity, limit), None


def position_size(
    state: PortfolioState, quantity: Decimal, limit_price: Decimal | None
) -> PositionSize:
    estimated = (
        (quantity * limit_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if limit_price is not None
        else None
    )
    percent = (
        estimated / state.account_equity * 100
        if estimated is not None and state.account_equity
        else None
    )
    return PositionSize(
        quantity=quantity,
        estimated_value=estimated if estimated else None,
        percent_of_portfolio=(
            float(percent) if percent is not None and percent <= 100 else None
        ),
        sizing_base_value=state.account_equity if state.account_equity else None,
    )
