# 券商网关

支持 Schwab、Vanguard 的本地 CSV 导入、草稿审阅，以及默认关闭的 Schwab 只读同步。不提交订单。

## Schwab 只读同步

先完成 CSV 导入、每日流程和本地仪表盘验收，再按[部署说明](../docs/09_Deployment_Guide.md#18-schwab-api-deployment-notes)选择是否启用。同步使用外部授权取得的访问令牌，到期即停止；不登录、不接收回调、不刷新或写盘保存令牌。

默认只读取已明确绑定的一个账户、持仓和现金。加 `--since` 可读美元单证券腿的成交，再加 `--orders` 可一并读取订单状态。只发送固定 Schwab HTTPS GET，不跟随重定向；即使令牌本身有交易权限，这个客户端也不能下单、改单或撤单。状态只供读取，不改变本地草稿。

账户号码和哈希不写库，不输出原始响应。现金缺值保留为空，不以购买力替代可交易现金。非支持持仓会计数提示，未出现在响应里的旧持仓不自动补零。成交与可关联的日志在同一事务入库；如果同账户的 CSV 可能重叠且没有一致的成交 ID，整批停止，保留原记录。

## 本地草稿与审批

Phase 9 通过 `broker_gateway.drafts.OrderDraftService` 读取已入库的当日交易计划，生成普通时段、当日有效的限价草稿。调用 `create_draft(plan_id)` 后先向用户展示返回的 `draft.order_snapshot()`。只有用户明确批准该快照后，调用 `record_decision(draft_id, Decision.APPROVED, reviewed_payload=已审阅的快照)`；`Decision` 来自 `shared.enums.ApprovalDecision`。本阶段不提供券商提交或 API 调用。

- WATCH 不生成草稿；需要小时确认的计划必须附可复核证据。旧计划若缺少新版规划证据，请重新生成。
- BUY 缺可交易现金时只可待审，不能批准；已知不足时不生成草稿。SELL 必须验证触发和可卖数量。
- 延期后可调用 `reopen_deferred(draft_id)` 重新进入待审。已被替代的计划可用 `expire_draft(draft_id)` 结束其未提交草稿。
- 修改会结束原草稿并创建新 ID，必须获得新审批。`require_current_approval(draft_id)` 检查已落库批准、精确参数和当前证据，仅作本地安全校验。

## 本地导入

先初始化 DuckDB。原始文件放在仓库的 `imports/raw/schwab/` 或 `imports/raw/vanguard/` 下，每份文件只包含一个账户。从仓库根目录运行：

```powershell
$env:PYTHONPATH = "broker-gateway/src;investment-journal/src;."
.\.venv\Scripts\python.exe -m broker_gateway.csv_import SCHWAB SCHWAB_ROTH imports/raw/schwab/transactions.csv
```

持仓或现金导入必须用 `--observed-at` 提供实际观察时间，例如 `2026-06-05T15:00:00-05:00`。系统用 `America/Chicago` 确定快照日期，入库时间统一存为 UTC。有账户号列时可加 `--verify-source-account`，在不回显的提示中输入 CSV 上的账户号；否则请在确认前手动核对导出文件归属。

本地终端会显示规范化记录、警告和已入库 ID。确认后输入 `IMPORT`；其他输入取消，原文件不移动。不要把真实预览或导出粘贴到聊天、工单或 Git。

## 首版支持的格式

- Schwab 交易识别 `Date,Action,Symbol` 及可用的 `Quantity,Price,Fees & Comm,Amount`；持仓识别 `Symbol,Qty (Quantity),Mkt Val (Market Value)` 及可用的市价、成本等字段。
- Vanguard 交易识别 `Trade Date,Transaction Type,Symbol`、`Shares,Share Price,Principal Amount,Commission Fees,Net Amount` 等列；持仓识别 `Symbol,Shares,Total Value`。同一文件内的持仓与交易段一起预览和提交。
- 独立现金 CSV 可使用 `Currency,Cash Balance,Available to Trade`；至少填一个金额，首版只支持 USD。Schwab 持仓中的 `Cash & Cash Investments` 只提供余额，不当作可交易资金。缺失持仓、金额或费用不补零。
- 支持 UTF-8 CSV（可以带 BOM），日期为 ISO 或美国月/日/年格式，持仓须是按标的汇总的股票、ETF 或基金记录。暂未用真实导出验证各页面的变体。遇到列名不匹配时，先用合成或脱敏样本验证，不要修改真实数据来绕过校验。

## 重复导入与归档

- 有券商成交 ID 时优先使用该 ID；同一 ID 的经济字段冲突会阻止整批导入。没有 ID 时，用规范字段和文件内出现序号匹配。同一文件内的两笔相同成交会保留两笔，但单独出现在两个文件的相同成交无法可靠区分。
- 成交日志与导入数据在同一 DuckDB 事务提交。提交成功后，原文件按内容哈希移到 `imports/archive/`；文件名和券商账户号不写入来源字段。归档失败但已入库时，修复目录权限后重新预览及确认，已有记录会去重。
