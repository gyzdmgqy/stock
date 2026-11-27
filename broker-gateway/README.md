# 券商网关

Phase 8 支持本地预览和导入 Schwab、Vanguard 的交易流水、持仓和现金快照。不连接券商 API，也不生成或提交订单。

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
