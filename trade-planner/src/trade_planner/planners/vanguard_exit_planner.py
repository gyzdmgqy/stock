from shared.enums import Action, StrategyType

from .base import Decision, PlanningContext


def plan_exit_only(context: PlanningContext) -> Decision:
    position = context.request.portfolio
    if position is None:
        return Decision(Action.WATCH, "需要确认账户持仓，个股买入始终受限。")
    if position.quantity == 0:
        return Decision(Action.AVOID, "退出专用账户禁止新增个股。")

    return Decision(
        Action.EXIT_ONLY,
        "已有个股只可评估退出，置换分配以账户显式配置为准。",
        strategy_type=StrategyType.VANGUARD_EXIT_ONLY,
        exit_trigger=(
            "two_completed_closes_below_ma200",
            "investment_thesis_invalidated",
        ),
        invalid_condition=("holding_closed", "account_policy_changed"),
        replacement=context.account.default_replacement,
        future_reentry_account=context.future_reentry_account,
    )
