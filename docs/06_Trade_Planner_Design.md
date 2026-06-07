# Personal CIO System
## Trade Planner Design V1.0

---

# 1. Purpose

This document defines the design of the **Trade Planner** module for the Personal CIO System.

The Trade Planner is the core decision-planning module of the system.

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

Optional for MVP, but schema should support hourly execution signals.

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
- no order draft if confidence below threshold
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

Recommended strategy types:

```text
INDEX_DCA
TREND_FOLLOWING
RANGE_TRADING
FALSE_BREAKDOWN_REENTRY
GAP_CONTINUATION
GAP_EXHAUSTION_AVOID
VANGUARD_EXIT_ONLY
ACCOUNT_MIGRATION
RISK_REDUCTION
EARNINGS_RISK_CONTROL
```

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
- Replacement plan should default to VOO / QQQ.
- Future re-entry account should be Schwab Roth IRA.
- Monitor relative performance vs VOO and QQQ.
- Support time-based exit if no technical exit appears.

Recommended replacement ratio:

```yaml
VOO: 70%
QQQ: 30%
```

Alternative growth-tilted ratio:

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

## 8.3 Confidence Gate

```text
confidence < 50:
  no order draft

50 <= confidence < 70:
  WATCH only or small-size plan

70 <= confidence < 85:
  eligible for order draft

confidence >= 85:
  eligible for stronger action, still requiring user approval
```

---

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

Supported stop types:

```text
NONE
PRICE_STOP
STOP_LIMIT
STRUCTURE_CONFIRMATION
TIME_STOP
```

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

Use percent-of-portfolio sizing.

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
portfolio_value = 450,000
max_trade_risk = 0.5% = 2,250
entry_price = 462
stop_price = 447
risk_per_share = 15
quantity = 2,250 / 15 = 150 shares
```

The system should cap position size by maximum portfolio weight.

## 13.3 Fractional Kelly

Future version may support Fractional Kelly.

For MVP, use fixed risk percentage and confidence score.

---

# 14. Risk Controls

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
min_confidence_for_order_draft: 70
```

---

# 15. Order Draft Eligibility

A Trade Plan is eligible for order draft only if:

- account_role allows the action
- confidence >= minimum threshold
- action is ADD, REDUCE, EXIT, or RE_ENTRY
- price fields are valid
- position size is valid
- risk rules pass
- no blocking event exists
- user has not disabled order drafts

WATCH plans should normally not generate order drafts.

Exception:

A WATCH plan may generate a conditional draft only if user explicitly enables conditional order drafts.

---

# 16. Plan Status Lifecycle

```text
DRAFT
  ↓
REVIEWED
  ↓
APPROVED / REJECTED / EXPIRED
  ↓
EXECUTED
```

Status definitions:

- DRAFT: system-generated, not yet reviewed
- REVIEWED: user has reviewed
- APPROVED: user approved
- REJECTED: user rejected
- EXPIRED: conditions no longer valid
- EXECUTED: broker execution recorded

---

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

## 18.3 broker-gateway-schwab

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

```python
from datetime import date
from typing import Optional, List, Dict
from pydantic import BaseModel


class OrderIntent(BaseModel):
    type: str
    price: Optional[float] = None
    stop_price: Optional[float] = None
    limit_price: Optional[float] = None
    condition: Optional[str] = None


class PositionSize(BaseModel):
    percent_of_portfolio: Optional[float] = None
    estimated_value: Optional[float] = None
    quantity: Optional[float] = None


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
    entry_condition: List[str] = []
    entry_order: Optional[OrderIntent] = None
    stop_order: Optional[OrderIntent] = None
    position_size: Optional[PositionSize] = None
    risk_reward_ratio: Optional[float] = None
    confidence: Optional[float] = None
    invalid_condition: List[str] = []
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
