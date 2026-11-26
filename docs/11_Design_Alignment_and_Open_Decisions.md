# Design Alignment and Open Decisions

## Confirmed Decisions

- Runtime: market data -> analysis -> trade planner -> broker-gateway order drafts -> CIO brief -> journal.
- Doc 04 is the single canonical schema; it incorporates the richer journal schema from doc 08.
- Doc 10 is the canonical build order, Phases 0-13. Runtime order and build order serve different purposes.
- Application/report/scheduler timezone is America/Chicago, independent of host timezone or travel.
- Complete stable CSV import, daily pipeline, and local dashboard before Schwab read-only API.
- Use neutral broker-gateway with adapters/schwab and adapters/vanguard; Vanguard remains CSV/manual.
- Current workspace folder remains Stock; personal-cio-system is the product name, not a rename requirement.

- Size positions from individual account equity; check combined-portfolio exposure separately.
- REDUCE / EXIT has separate protective-exit eligibility, independent of the 70-point entry-confidence threshold. Exact triggers remain to be specified.
- Plans requiring hourly confirmation remain WATCH with no draft until required confirmations are satisfied; no daily-only fallback or conditional-draft bypass.

## 已确认的存储设计

Phase 2 已确认采用关系字段与 JSON 的组合。金额、价格和数量使用定点列，
条件列表和来源引用保存在 JSON 列中，Python 继续使用嵌套交易计划模型。

For example, a message may contain:

```json
{
  "entry_order": {"type": "LIMIT", "price": 462.0},
  "entry_condition": ["daily_close_above_ma200", "volume_confirmed"],
  "replacement": {"VOO": 0.7, "QQQ": 0.3}
}
```

Three possible storage designs:

| Design | Example | Tradeoff |
|---|---|---|
| Nested JSON columns | entry_order contains {"type":"LIMIT","price":462.0} | Flexible; querying/validating prices needs JSON extraction |
| Normalized child tables | plan_order(plan_id, role, type, price); plan_condition(plan_id, sequence, rule) | Strong relational links and repeatable children; more joins and mappings |
| Flat model and table | entry_order_type=LIMIT, entry_price=462; one column per fixed attribute | Simple filtering; variable conditions/allocations do not fit well into fixed columns |

例如，`entry_price` 使用 `DECIMAL` 列，`entry_condition` 使用 JSON 数组，
`replacement` 使用 JSON 对象。`trade_plan_signal_link` 等关联记录仍使用关系表。

Trade plans need filterable account, action, status, prices and sizing. Briefs
benefit from structured JSON sections. Order drafts need explicit executable
columns plus a derived broker payload. A fully normalized condition/order-leg
model can be introduced later if multi-leg orders become a real requirement.

Do not maintain two writable sources for the same value. Repository mapping must
round-trip the complete model, validate JSON shape, and reject mismatches. An
approval snapshot is an immutable record of what the user reviewed, not another
editable order.

## Enum and Status Recommendation

Doc 04 section 15 owns the complete registry and transition table; the other docs
reference it. It includes the richer journal entry types, DEFERRED approval,
consistent strategy names, and separate planning StopType versus broker OrderType.

Recommended additions and semantics:

- MODIFIED retires a draft and creates a new PENDING_REVIEW draft requiring approval.
- EXPIRED prevents stale unsubmitted drafts from remaining approved indefinitely.
- SUBMITTING records an in-progress request; UNKNOWN means acceptance is unresolved.
- UNKNOWN must reconcile with the broker before a retry.
- Partial fills remain real transactions even if the remainder is canceled.
- EXIT_ONLY is a policy/plan action, not a SELL instruction by itself.
- Daily and hourly action hints have separate vocabularies.

These lifecycle refinements are reviewable design recommendations. No trading
implementation has started.

## 已确认的 Phase 4 规则

- MA200 附近区间为 ±1%，长下影线下限为全天振幅的 40%，接近最高为全天区间的顶部 25%。
- 当日成交量达到此前五日均量的 2 倍时达到恐慌量阈值。
- 相同输入生成同一信号 ID，行情更正后生成新版本并保留旧记录。

## Remaining Product Decisions

| Decision | Recommendation / question | Needed before |
|---|---|---|
| Protective exit details | Separate rules are confirmed. Agree exact triggers, thresholds, freshness, and reduction quantities; do not use an arbitrary lower confidence cutoff. | Phase 5 |
| 交易策略定义 | 细化行动触发、置信度和风险评分。需要小时线确认的计划继续保持 `WATCH`，直到条件满足。 | Phase 5 |
| Event and freshness inputs | Which earnings/event source or manual calendar is available? Recommend blocking new-entry drafts when required event, price, position, or cash data is missing/stale; define maximum ages. | Phase 3-5 |
| Outcome measurement | Separate plan forward returns from realized execution returns. Agree reference price, costs, dividends/splits, partial fills, and benchmark/horizon conventions. | Phase 6 |
| Vanguard migration | Allocation is undecided. Explain replacement of legacy-stock sale proceeds versus a whole-account target; agree assets, weights, observation period, and timing. 70/30 and 60/40 are examples, not defaults. | Phase 5 |
| Approval validity | Agree expiry window and whether submission requires a separate user click after approval. Propose explicit submit plus fresh validation. | Phase 9-13 |
| CSV samples | Obtain redacted format examples to define columns, cash signs, deduplication, and cross-source reconciliation. | Phase 8 |

## Vanguard Allocation Example

The original docs suggested replacing exited Vanguard individual stocks with
VOO and QQQ. For $10,000 of sale proceeds selected for reinvestment, the example
70/30 split means $7,000 in VOO and $3,000 in QQQ; 60/40 means $6,000 and $4,000.
These are allocations by dollars, not share counts, account splits, or return
predictions. This example does not establish a target for the entire account.

The user has not selected an allocation. Keep default_replacement null and make
any future chosen ratio configurable. Vanguard execution remains manual. Selling
an individual stock does not authorize or automatically cause replacement buys.

## Documentation Ownership

- 01: product scope and outcomes.
- 02: module boundaries and runtime data flow.
- 03: repository and coding conventions.
- 04: all CREATE TABLE definitions, field mappings, enum values, and persisted state transitions.
- 05: message envelopes and examples derived from doc 04.
- 06: planning rules and account behavior.
- 07: broker adapters, import, approval, submission behavior.
- 08: journal interpretation, outcomes, and review behavior; no duplicate CREATE TABLE definitions.
- 09: local setup, configuration, scheduling, backup, and deployment.
- 10: the only numbered implementation sequence.
- 11: confirmed decisions, recommendations awaiting review, and open product questions.

Examples and abbreviated model sketches do not override the canonical schema.
Future schema edits must update doc 04 and their affected examples together.
