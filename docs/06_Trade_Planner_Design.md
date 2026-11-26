# Personal CIO System
## Trade Planner Design V1.0

---

# 1. Purpose

Phase 5 的实际规则、输入字段和初始参数集中记录在
[交易规划实现说明](../trade-planner/README.md)。

This document defines the design of the **Trade Planner** module for the Personal CIO System.

The Trade Planner is the core decision-planning module of the system.

Doc 04 owns the canonical schema, enums, and persistence mapping. Doc 10 owns
build order. Model and JSON examples here illustrate the nested service contract.

Its role is to convert structured market signals, portfolio state, account rules, risk constraints, and user strategy preferences into high-quality, human-reviewable trade plans.

The Trade Planner does **not** automatically trade.

It produces:

- Trade Plans
- Exit Plans
- Re-entry Plans
- Order Draft Inputs
- Position Sizing Recommendations
- Invalid Conditions
- Risk Notes

All plans must be reviewed and approved by the user before any broker action.

---

# 2. Design Philosophy

## 2.1 Trade Planner is not a prediction engine

The Trade Planner should not attempt to predict exact future prices.

Instead, it answers:

```text
Given the current market structure, portfolio state, and rules,
what is the best actionable plan?
```

---

## 2.2 Trade Planner is not an Agent

The Trade Planner is primarily a **rule-driven planning engine**.

LLM/Agent components may explain the plan, but the plan itself should be generated from explicit rules and structured inputs.

Recommended principle:

```text
Rules generate plans.
Agents explain plans.
Humans approve plans.
```

---

## 2.3 Daily decides direction, hourly improves execution

For MVP:

```text
Daily timeframe = strategic direction
Hourly timeframe = execution refinement
```

Examples:

- Daily MA200 determines whether a stock is structurally healthy.
- Hourly higher-low structure may help refine limit entry.
- Daily false breakdown signal may identify re-entry candidates.
- Hourly VWAP recovery may improve execution confidence.

---

# 3. Trade Planner Inputs

The Trade Planner consumes the following structured inputs.

## 3.1 Daily Signals

From `analysis-engine`.

Examples:

- market_regime
- trend_state
- price_location
- false_breakdown_score
- gap_type
- volume_confirmation_score
- risk_score
- action_hint
- confidence

Example:

```json
{
  "symbol": "VRTX",
  "trade_date": "2026-06-07",
  "market_regime": "RANGE",
  "trend_state": "WEAK_UP",
  "price_location": "NEAR_MA200",
  "false_breakdown_score": 76,
  "volume_confirmation_score": 68,
  "risk_score": 42,
  "action_hint": "WATCH",
  "confidence": 74
}
```

---

## 3.2 Intraday Signals

Hourly ingestion is optional for MVP, but plans that require hourly confirmation
must remain WATCH until all required hourly conditions are confirmed using valid
data. Missing, stale, or unconfirmed hourly signals mean no order draft for that
plan, including conditional drafts. Daily-only strategies may act only when their
own rule definitions do not require hourly confirmation.

Examples:

- hourly_trend
- VWAP status
- intraday_recovery_score
- execution_quality_score
- hourly higher-low confirmation

Example:

```json
{
  "symbol": "VRTX",
  "interval": "1h",
  "vwap_status": "ABOVE_VWAP",
  "hourly_trend": "HIGHER_LOW_FORMING",
  "execution_quality_score": 69
}
```

---

## 3.3 Portfolio State

From broker API, CSV import, or manual input.

Includes:

- account_id
- broker
- account_role
- current quantity
- market value
- portfolio weight
- cash available
- unrealized gain/loss

---

## 3.4 Account Role Rules

Allocation ratios shown here are illustrative and unapproved. The user's
Vanguard replacement allocation remains undecided; do not apply 70/30 or 60/40
as an operational default. Keep replacement suggestions unallocated until chosen.

The Trade Planner must respect account-level rules.

Example:

```yaml
VANGUARD_ROTH:
  account_role: CORE_PASSIVE
  individual_stock_policy: EXIT_ONLY
  new_individual_stock_buy_allowed: false
  replacement:
    VOO: 0.7
    QQQ: 0.3

SCHWAB_ROTH:
  account_role: ACTIVE_TRADING
  individual_stock_policy: ACTIVE_ALLOWED
  new_individual_stock_buy_allowed: true
  order_draft_enabled: true
```

---

## 3.5 Risk Rules

Examples:

- maximum position size per stock
- maximum sector exposure
- maximum single-trade risk
- no new entry before earnings unless explicitly allowed
- no new-entry draft if entry confidence is below threshold
- separate REDUCE / EXIT eligibility rules based on confirmed exit triggers
- no order draft if account role blocks action

---

# 4. Trade Planner Outputs

## 4.1 Trade Plan

A structured plan for a possible action.

Example:

```json
{
  "plan_id": "TP-20260607-VRTX-001",
  "symbol": "VRTX",
  "account_id": "SCHWAB_ROTH",
  "account_role": "ACTIVE_TRADING",
  "plan_date": "2026-06-07",
  "action": "WATCH",
  "strategy_type": "FALSE_BREAKDOWN_REENTRY",
  "thesis": "VRTX recovered above MA200 after a false breakdown and may become a re-entry candidate if volume confirms.",
  "reason": "False breakdown score is high and volume confirmation is moderate.",
  "primary_timeframe": "daily",
  "execution_timeframe": "1h",
  "entry_condition": [
    "daily_close_above_ma200",
    "volume_above_1.3x_avg5",
    "hourly_higher_low_confirmed"
  ],
  "entry_order": {
    "type": "LIMIT",
    "price": 462.0
  },
  "stop_order": {
    "type": "STOP_LIMIT",
    "stop_price": 447.0,
    "limit_price": 445.0
  },
  "position_size": {
    "percent_of_portfolio": 1.5,
    "estimated_value": 6750.0
  },
  "risk_reward_ratio": 3.1,
  "confidence": 74,
  "invalid_condition": [
    "close_below_ma200_for_2_days",
    "earnings_risk_high_without_position_reduction"
  ],
  "status": "DRAFT"
}
```

---

## 4.2 Exit Plan

Used especially for Vanguard individual stocks under account migration policy.

Example:

```json
{
  "plan_id": "TP-20260607-VANGUARD-VRTX-EXIT-001",
  "account_id": "VANGUARD_ROTH",
  "account_role": "CORE_PASSIVE",
  "symbol": "VRTX",
  "action": "EXIT_ONLY",
  "strategy_type": "ACCOUNT_MIGRATION",
  "reason": "Vanguard account is migrating to passive core VOO/QQQ strategy.",
  "exit_trigger": [
    "fundamental_thesis_broken",
    "close_below_ma200_for_2_days",
    "relative_strength_underperforms_qqq_60d",
    "max_observation_period_reached"
  ],
  "replacement": {
    "VOO": 0.7,
    "QQQ": 0.3
  },
  "future_reentry_account": "SCHWAB_ROTH",
  "status": "DRAFT"
}
```

---

## 4.3 Order Draft Input

The Trade Planner does not directly create broker payloads.

It outputs broker-neutral order intent.

The Broker Gateway converts it into broker-specific payloads.

Example:

```json
{
  "plan_id": "TP-20260607-VRTX-001",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "instruction": "BUY",
  "order_type": "LIMIT",
  "quantity": 10,
  "limit_price": 462.0,
  "time_in_force": "DAY"
}
```

---

# 5. Action Types

The Trade Planner may output the following actions:

```text
HOLD
WATCH
ADD
REDUCE
EXIT
RE_ENTRY
AVOID
EXIT_ONLY
```

## HOLD

Current position is acceptable. No action needed.

## WATCH

No immediate trade. Conditions must be monitored.

## ADD

Position may be increased if entry conditions are met.

## REDUCE

Position risk should be reduced.

## EXIT

Position should be exited if exit conditions are met.

## RE_ENTRY

A previously exited or stopped-out position may become eligible for re-entry.

## AVOID

Do not enter due to risk, weak signal, earnings, macro event, or poor structure.

## EXIT_ONLY

Used for accounts where new individual stock purchases are disabled, especially Vanguard Core Passive migration.

---

# 6. Strategy Types

Use StrategyType from [doc 04](04_Database_Design.md#canonical-enums-and-status-transitions).

---

# 7. Account Role Behavior

## 7.1 Vanguard Roth IRA

Role:

```text
CORE_PASSIVE
```

Policy:

```text
Individual stocks: EXIT_ONLY
New individual stock buys: disabled
Replacement assets: VOO / QQQ
Daily trade plans: only exit plans
```

Trade Planner behavior:

- Do not generate new buy plans for individual stocks.
- Generate exit plans for existing individual stocks.
- Replacement assets are illustrated as VOO / QQQ; allocation weights await the user's decision.
- Future re-entry account should be Schwab Roth IRA.
- Monitor relative performance vs VOO and QQQ.
- Support time-based exit if no technical exit appears.

Unapproved example replacement ratio:

```yaml
VOO: 70%
QQQ: 30%
```

Another unapproved example ratio:

```yaml
VOO: 60%
QQQ: 40%
```

---

## 7.2 Schwab Roth IRA

Role:

```text
ACTIVE_TRADING
```

Policy:

```text
Individual stocks: allowed
Order drafts: enabled
Trade Planner: fully enabled
```

Trade Planner behavior:

- Generate buy, add, reduce, exit, re-entry plans.
- Generate order draft inputs for high-quality plans.
- Use daily signals for direction.
- Use hourly signals for execution refinement.
- Record all decisions for performance review.

---

# 8. Planning Logic

## 8.1 Top-Level Decision Flow

```text
1. Check account role.
2. Check market regime.
3. Check existing position state.
4. Check technical signal.
5. Check risk constraints.
6. Determine action.
7. Calculate entry / exit / stop.
8. Calculate position size.
9. Generate invalid conditions.
10. Generate Trade Plan.
```

---

## 8.2 Account Role Gate

Pseudo-code:

```python
if account_role == "CORE_PASSIVE":
    if symbol not in ["VOO", "QQQ"] and current_position > 0:
        action = "EXIT_ONLY"
    elif symbol not in ["VOO", "QQQ"] and current_position == 0:
        action = "AVOID"
    else:
        action = "HOLD"
```

---

## 8.3 Entry Confidence and Protective Exit Gates

首版假跌破入场在置信度缺失时取两项形态评分的较低值，评分任一缺失时继续观察。
`EXIT` 使用连续两个已收盘交易日低于各自 MA200 的触发，而 `REDUCE` 以账户
单股市值超限为触发。两者独立于入场置信度、小时线及财报禁入条件，并校验持仓时效、
可卖股数和未完成订单状态。

The following confidence bands apply only to ADD / RE_ENTRY:

```text
confidence < 50:
  no order draft

50 <= confidence < 70:
  WATCH or small-size planning scenario; no entry order draft

70 <= confidence < 85:
  eligible for order draft

confidence >= 85:
  eligible for stronger action, still requiring user approval
```

---

Protective REDUCE / EXIT plans do not inherit the 70-point entry threshold.
Their rules must establish a specific exit/risk-reduction trigger, a held
position, valid sell quantity, and action-appropriate risk checks. Account
restrictions, price/position freshness, draft validation, and human approval
still apply. 首版退出触发和减仓口径见本节上方，其他保护性策略后续单独确认。

## 8.4 Event Risk Gate

If earnings or major event is near:

```text
new entry blocked unless override is enabled
position size reduced
confidence capped
```

Example rule:

```text
If earnings within 5 trading days:
  New entry plan becomes WATCH, not ADD.
```

---

# 9. Entry Logic

## 9.1 Trend Following Entry

Conditions may include:

- Close above MA50
- Close above MA200
- MA20 > MA50
- MA50 > MA200
- ADX confirms trend
- Pullback to MA20 or MA50
- Volume does not show distribution

Output:

```text
ADD or WATCH
```

---

## 9.2 False Breakdown Re-entry

Phase 4 的假跌破评分要求最低价跌破前一交易日的 MA200、收盘收复、
下影线达到阈值且无恐慌量。分析层给出 `WATCH`，后续规划层仍需满足
各自的行情、账户、风险和小时线确认条件。详见[分析引擎规则](../analysis-engine/README.md)。

Conditions may include:

- Intraday break below MA200
- Close back above MA200
- Long lower shadow
- False breakdown score > 70
- Volume confirmation score > 60
- Hourly higher-low confirmation
- Price remains above VWAP

Output:

```text
WATCH or RE_ENTRY
```

---

## 9.3 Range Trading Entry

Conditions may include:

- Price near lower range
- No structural breakdown
- Support zone holds
- Volume does not confirm breakdown
- Risk/reward acceptable

Output:

```text
WATCH or ADD
```

---

## 9.4 Gap Entry

Gap Up:

- Avoid exhaustion gap.
- Consider continuation only if price holds VWAP and volume confirms.

Gap Down:

- Avoid panic breakdown.
- Consider re-entry only if price recovers key level and intraday structure improves.

Output:

```text
WATCH, AVOID, or RE_ENTRY
```

---

# 10. Exit Logic

## 10.1 Technical Exit

Conditions:

- Close below MA200 for 2 days
- Failed reclaim of MA200
- Break of structural support
- Distribution volume
- Lower-high / lower-low structure

---

## 10.2 Vanguard Exit Logic

For Vanguard individual stocks:

Exit triggers:

- Fundamental thesis broken
- Close below MA200 for 2 days
- Relative strength underperforms VOO or QQQ over 60 trading days
- Maximum observation period reached
- User no longer wants to manage the stock
- Position no longer deserves Roth IRA space

Replacement:

```text
Sell individual stock
Buy VOO / QQQ according to configured ratio
```

---

## 10.3 Risk Reduction Exit

Conditions:

- Position exceeds max allowed weight
- Earnings risk too high
- Sector concentration too high
- Macro regime becomes HIGH_RISK

Output:

```text
REDUCE
```

---

# 11. Stop Logic

## 11.1 Stop Types

Use StopType from doc 04: NONE, PRICE_STOP, STOP_LIMIT,
STRUCTURE_CONFIRMATION, TIME_STOP. This differs from broker OrderType.
Structure/time conditions generate reviewable intents when triggered; they are
not executable broker order types.

## 11.2 Structure Confirmation Stop

Recommended for range trading and false breakdown strategies.

Example:

```text
Exit only if close below MA200 for 2 consecutive days.
```

This avoids being stopped out by intraday noise.

## 11.3 Stop Limit Logic

Stop Limit should include:

- stop_price
- limit_price
- rationale

Example:

```json
{
  "type": "STOP_LIMIT",
  "stop_price": 447.0,
  "limit_price": 445.0,
  "reason": "Below key support zone and MA200 buffer."
}
```

---

# 12. Limit Price Logic

Limit price may be derived from:

- current close
- previous support
- MA20 / MA50 / MA200
- hourly pullback zone
- VWAP
- ATR buffer
- risk/reward target

Example:

```text
limit_price = min(current_price, hourly_support + 0.25 * ATR)
```

The exact formula should be strategy-specific and backtested.

---

# 13. Position Sizing

## 13.1 Simple MVP Rule

Use percent-of-account-equity sizing. Account equity includes holdings plus cash.
For example, 1.5% of a $450,000 Schwab account is $6,750, even if the combined
portfolio is $780,000. Cash availability and position limits can further reduce
that amount. Also check combined stock/sector exposure across accounts.

The existing percent_of_portfolio field means percentage points of this account
in the MVP; sizing_basis=ACCOUNT makes the denominator explicit. Combined exposure
checks are separate and never substitute a larger sizing denominator.

Example:

```text
Low confidence: 0.5% - 1.0%
Medium confidence: 1.0% - 1.5%
High confidence: 1.5% - 3.0%
```

## 13.2 Risk-Based Sizing

Future version:

```text
position_value = max_risk_dollars / distance_to_stop_percent
```

Example:

```text
account_equity = 450,000
max_trade_risk = 0.5% = 2,250
entry_price = 462
stop_price = 447
risk_per_share = 15
quantity = 2,250 / 15 = 150 shares
```

Cap position size by the account's maximum position weight and separately
validate combined-portfolio exposure.

## 13.3 Fractional Kelly

Future version may support Fractional Kelly.

For MVP, use fixed risk percentage and confidence score.

---

# 14. Risk Controls

组合单股 8% 和同板块 25% 是首版可配置上限。计算账户可买股数后，
按拟议成交金额另查两项组合敞口。组合数据缺失或超限时输出 `WATCH`。

Trade Planner must check:

- Max single stock exposure
- Max sector exposure
- Max single trade risk
- Earnings proximity
- Macro event proximity
- Account role restrictions
- Existing open orders
- Cash availability
- Stop distance too tight or too wide
- Risk/reward ratio below threshold

Recommended default constraints:

```yaml
max_single_stock_weight: 0.08
max_new_trade_weight: 0.03
max_trade_risk_percent: 0.005
min_risk_reward_ratio: 2.0
block_new_entry_before_earnings_days: 5
min_entry_confidence_for_order_draft: 70
```

---

# 15. Order Draft Eligibility

A Trade Plan is eligible for order draft only if:

- account_role allows the action
- ADD / RE_ENTRY confidence >= entry threshold (default 70)
- REDUCE / EXIT satisfies its separate protective-exit rules
- all required hourly confirmations are satisfied
- action is ADD, REDUCE, EXIT, or RE_ENTRY
- price fields are valid
- position size is valid
- action-specific risk rules pass (entry risk/reward rules do not automatically block protective exits)
- no action-specific blocking event exists
- user has not disabled order drafts

WATCH plans should normally not generate order drafts.

Exception:

A WATCH plan may generate a conditional draft only if the user explicitly enables
conditional drafts and all required hourly confirmations are already satisfied.
A WATCH state caused by missing, stale, or unconfirmed required hourly evidence
never qualifies for this exception.

---

# 16. Plan Status Lifecycle

Use the canonical TradePlanStatus transitions in doc 04. DRAFT becomes REVIEWED,
then APPROVED or REJECTED. Invalid or superseded unexecuted plans become EXPIRED.
Only an APPROVED plan whose intended execution is complete becomes EXECUTED.
Partial fills remain execution records without prematurely completing the plan.
Approving a plan never substitutes for approving an order draft.

# 17. Example Plans

## 17.1 Schwab Re-entry Plan

```json
{
  "plan_id": "TP-20260607-SCHWAB-VRTX-REENTRY-001",
  "account_id": "SCHWAB_ROTH",
  "symbol": "VRTX",
  "action": "RE_ENTRY",
  "strategy_type": "FALSE_BREAKDOWN_REENTRY",
  "entry_condition": [
    "close_above_ma200",
    "volume_confirmation_score_above_70",
    "hourly_higher_low_confirmed"
  ],
  "entry_order": {
    "type": "LIMIT",
    "price": 462.0
  },
  "stop_order": {
    "type": "STRUCTURE_CONFIRMATION",
    "condition": "close_below_ma200_for_2_days"
  },
  "position_size": {
    "percent_of_portfolio": 1.5
  },
  "confidence": 76,
  "status": "DRAFT"
}
```

---

## 17.2 Vanguard Exit-Only Plan

```json
{
  "plan_id": "TP-20260607-VANGUARD-AAPL-EXIT-001",
  "account_id": "VANGUARD_ROTH",
  "symbol": "AAPL",
  "action": "EXIT_ONLY",
  "strategy_type": "ACCOUNT_MIGRATION",
  "reason": "Vanguard is being converted into long-term VOO/QQQ core account.",
  "exit_trigger": [
    "relative_strength_underperforms_qqq_60d",
    "close_below_ma200_for_2_days",
    "max_observation_period_reached"
  ],
  "replacement": {
    "VOO": 0.7,
    "QQQ": 0.3
  },
  "future_reentry_account": "SCHWAB_ROTH",
  "status": "DRAFT"
}
```

---

# 18. Integration with Other Modules

## 18.1 analysis-engine

Trade Planner consumes:

- daily_signal
- intraday_signal
- risk_snapshot

## 18.2 market-data-service

Trade Planner indirectly depends on:

- price data
- indicators
- events
- portfolio snapshots

## 18.3 broker-gateway

Trade Planner provides broker-neutral order intent.

Broker Gateway converts it to Schwab-specific payload.

## 18.4 personal-cio-agent

CIO Agent summarizes Trade Plans into Daily CIO Brief.

## 18.5 investment-journal

Journal records:

- generated plans
- user decisions
- plan outcomes
- execution results

---

# 19. Pydantic Model Draft

This sketch shows nesting only. Implement canonical enums and all fields from
doc 04, use Decimal for executable prices/quantities, and validate actionable
plans. Exit examples are abbreviated and must also carry plan_date and applicable
invalid conditions before persistence.

```python
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class OrderIntent(BaseModel):
    type: str
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    limit_price: Optional[Decimal] = None
    condition: Optional[str] = None
    reason: Optional[str] = None


class PositionSize(BaseModel):
    percent_of_portfolio: Optional[float] = None
    estimated_value: Optional[Decimal] = None
    quantity: Optional[Decimal] = None


class TradePlan(BaseModel):
    plan_id: str
    symbol: str
    account_id: str
    account_role: str
    plan_date: date
    action: str
    strategy_type: str
    thesis: Optional[str] = None
    reason: Optional[str] = None
    primary_timeframe: str = "daily"
    execution_timeframe: Optional[str] = None
    entry_condition: List[str] = Field(default_factory=list)
    entry_order: Optional[OrderIntent] = None
    stop_order: Optional[OrderIntent] = None
    position_size: Optional[PositionSize] = None
    risk_reward_ratio: Optional[float] = None
    confidence: Optional[float] = None
    invalid_condition: List[str] = Field(default_factory=list)
    exit_trigger: List[str] = Field(default_factory=list)
    replacement: Optional[Dict[str, float]] = None
    future_reentry_account: Optional[str] = None
    status: str = "DRAFT"
```

---

# 20. Success Criteria

The Trade Planner is successful if:

- Every plan is structured.
- Every plan is explainable.
- Every plan has invalid conditions.
- Every actionable plan includes position sizing.
- Every order draft can be traced to a plan.
- Account role restrictions are always respected.
- Vanguard individual stocks are exit-only.
- Schwab is used as the active trading account.
- Daily data drives direction.
- Hourly data improves execution.
- The user can review plans quickly in the Daily CIO Brief.

The final output should help answer:

```text
What should I do?
Why?
When?
How much?
What invalidates the idea?
What order should be drafted?
```
