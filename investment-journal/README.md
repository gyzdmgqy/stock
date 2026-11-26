# 投资日志

Phase 6 记录信号、交易计划、草稿、审批、券商记录和每日 CIO 简报，并从历史价格
生成回看结果。运行 Python 时把 `investment-journal/src` 加入 `PYTHONPATH`，
各服务共用已经初始化的 DuckDB 连接。

## 日志和关联

`JournalService` 提供 `record_signal`、`record_plan`、`record_draft`、
`record_approval`、`record_transaction` 和 `record_brief`。
计划、草稿和券商记录应由各自模块先入库。日志 ID 由事件类型和来源 ID 生成，
重放时保留用户批注。审批与草稿分开记录，审批日期使用 `America/Chicago`。

成交关联使用已有草稿、已有计划或显式传入的 `plan_id`。服务校验账户、标的、
券商及各来源的关联一致性，在同一事务内保存券商关联和日志。后补关联会保留批注。

## 成交和计划回看

`OutcomeService.evaluate_plan` 和 `evaluate_transaction` 接收来源 ID、最后
已完成交易日 `as_of` 和调用方提供的按升序排列的交易日历。

- 计划使用计划日普通收盘价为起点，含被拒绝的计划。计划限价继续保留为意图。
- 每笔成交使用成交价为起点。买入后的上涨和卖出后的下跌为正值，结果是逐笔
  方向回看。手续费、股息、成交配对及已实现净损益留待完整核算。
- 按起算日之后的第 5、20、60 个交易日计算。目标日缺价时结果留空；目标日有价但
  中间有缺口时，保留首尾收益，最大回撤与最大涨幅留空。两项路径指标基于标的价格。
- 首次写入后的参考价保持固定。早期截止日重跑不会抹除已成熟的窗口。若后来发现
  已知拆股事件，跨越该事件的窗口清空，等待统一复权口径。

结果写入 `trade_outcome`，计划与成交拥有独立 ID。对应日志的收益摘要随之更新。

## 周报、月报和 Vanguard 持仓

`PerformanceReviewService.weekly_review` 和 `monthly_review` 接收起止日期
与可选的账户 ID，保存计数和 Markdown 摘要到 `performance_review`。
计划数按版本计，审批数按已记录的事件计，成交数按买卖记录计。VOO、QQQ、SPY 的
5、20、60 日基准比较为待接入项，胜率和净损益留空。

`vanguard_progress` 对比所选区间内首尾可用快照的个股数量和市值，展示最新
VOO 和 QQQ 市值及可计算的市值比。缺少数据时显示待确认。进度仅反映已观察的
持仓；快照减少本身无法区分卖出、转仓或数据缺失。
