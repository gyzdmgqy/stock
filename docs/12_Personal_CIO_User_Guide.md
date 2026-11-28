# Personal CIO 使用手册

Personal CIO 是本地投资审阅工具。它把市场行情和账户记录整理成信号、交易计划、待审草稿、每日简报和投资日志。**批准草稿只是本地记录，不会向券商下单。** 平常使用 CSV 导入；Schwab 只读 API 默认关闭，Phase 13 仅用于隔离环境中的模拟提交。

日常顺序：**更新账户 CSV → 收盘后运行日流程 → 看简报和计划 → 审阅草稿 → 导入真实成交并复盘**。

## 1. 首次启动

需要 Python 3.12 或更新版本。以下命令在仓库根目录的 Windows PowerShell 中运行。已创建虚拟环境时，跳过第一行。

```powershell
python -m venv .venv
..venvScriptspython.exe -m pip install -r requirements.txt
..venvScriptspython.exe scripts/init_workspace.py
..venvScriptspython.exe scripts/init_db.py
```

默认数据库为 `data/db/personal_cio.duckdb`。初始化可重复运行，应用待执行迁移并补齐种子，不清空历史数据，也不覆盖已入库账户设置。macOS 或 Linux 使用 `.venv/bin/python`，创建环境时可用 `python3`。

| 本地账户 | 用途与限制 |
|---|---|
| `SCHWAB_ROTH` | 主动交易账户。满足策略、账户和风控条件时可生成待审草稿。 |
| `VANGUARD_ROTH` | 核心账户。禁止新买个股；现有个股以 `EXIT_ONLY` 监控，不代表马上卖出。VOO/QQQ 的置换比例未设置，不会自动分配。 |

在 `config/symbols.yaml` 查看关注标的，在 `config/risk.yaml` 查看风险门槛。应用业务日期固定使用 `America/Chicago`，不随旅行或电脑时区变化。没有数据时，页面显示空白或提示缺失，不会生成示例账户记录。

## 2. 导入券商 CSV

从券商导出单一账户的持仓或交易文件，保存在 `imports/raw/schwab/` 或 `imports/raw/vanguard/`。首次使用真实导出时先看预览，核对列名、账户、标的、方向、数量和金额。首版适配已用合成样本验证，尚不能保证覆盖券商页面的所有导出格式。支持的列名见[券商网关说明](../broker-gateway/README.md)。

```powershell
$env:PYTHONPATH = "broker-gateway/src;investment-journal/src;."

# 交易 CSV：把示例文件名换成实际文件名。
..venvScriptspython.exe -m broker_gateway.csv_import SCHWAB SCHWAB_ROTH imports/raw/schwab/transactions.csv
..venvScriptspython.exe -m broker_gateway.csv_import VANGUARD VANGUARD_ROTH imports/raw/vanguard/transactions.csv

# 持仓或现金 CSV：把示例时间换成文件对应的实际观察时间。
..venvScriptspython.exe -m broker_gateway.csv_import SCHWAB SCHWAB_ROTH imports/raw/schwab/positions.csv --observed-at "2026-06-08T15:00:00-05:00"
```

- 持仓和现金必须提供带时区的 `--observed-at`。如果一个文件同时有持仓和成交，也要提供观察时间。带账户号列的文件可加 `--verify-source-account`，在不回显的提示中核对真正的券商账号。命令里的 `SCHWAB_ROTH` 和 `VANGUARD_ROTH` 是本地别名。
- 预览不写库。核对后输入 `IMPORT` 才会写入，其他输入会取消。提交成功后原文件移到 `imports/archive/`。如果提示已入库但归档失败，修复目录权限后重新预览确认，已有成交不会重复写入。
- 持仓没出现不等于已经清仓。独立现金 CSV 可用 `Currency,Cash Balance,Available to Trade`，首版只支持 USD；没有明确的可交易现金就留空，不把现金余额或购买力填进去。
- 成交优先按券商成交 ID 去重。没有 ID 时，两个文件里相同的成交可能无法区分，历史流水尽量使用不重叠的导出范围。账户号、真实 CSV 和导入预览不要贴到聊天或提交到 Git。

## 3. 按需补充已确认的账户事实

只想看行情和简报，可以跳过本节。CSV 通常不能证明可卖股数或是否有挂单。需要系统评估草稿时，可在 Git 忽略的 `imports/normalized/planning.yaml` 补充自己已核实的资料，或运行日流程时用 `--planning-inputs` 指定其他本地文件。

以下是**合成示例**，不能直接用于真实账户。每个账户和标的只写一项；确认时间应带时区、未过期，且不早于对应持仓快照。

```yaml
reviews:
  - account_id: SCHWAB_ROTH
    symbol: VRTX
    observed_at: "2026-06-08T15:05:00-05:00"
    has_open_order: false
    available_to_sell: 5
    exit_limit_price: 89
```

只填写确知的事实：没有挂单才填 `false`，已核实为空仓才填 `confirmed_flat: true`。不要把持有股数直接当作可卖股数。已有当日风险快照时，规划优先使用其净值；没有时可为该标的补充已核实的 `account_equity` 或 `combined_equity`，但这不会生成仪表盘的风险快照。

假跌破入场还需要对应策略证据，例如可验证的小时信号、财报窗口覆盖、入场与失效价格、可交易资金及组合敞口。没有小时确认时保持 `WATCH`，不生成条件草稿。保护性减仓和退出按独立触发判断，不套用入场置信度门槛。配置和细节见[部署指南](09_Deployment_Guide.md#12-daily-local-run)及[交易规划设计](06_Trade_Planner_Design.md)。

## 4. 收盘后运行日流程

```powershell
..venvScriptspython.exe scripts/run_daily_pipeline.py

# 不联网，只用 DuckDB 已有行情。仍会写库和生成报告。
..venvScriptspython.exe scripts/run_daily_pipeline.py --offline
```

正常模式仅补齐窗口缺失或不完整的日线，不覆盖完整记录。默认分析窗口为 220 个交易日，另读一日用于前一交易日的指标计算。非交易日或尚未收盘时跳过；交易所日历处理提前收市。脚本处理当前芝加哥业务日，没有 `--date` 历史回放参数。

跑完后，终端显示信号、计划、草稿和提醒数量。同日、同样的输入可重跑，不会重复写入，也保留已有人工备注。缺当日日线不借用旧信号；窗口不全时可有信号，但该标的本次不生成计划和草稿。草稿数为零并不一定是报错。

| 目录 | 产物 |
|---|---|
| `outputs/briefs/` | `YYYY-MM-DD_Daily_CIO_Brief.md` 及同名 JSON |
| `outputs/trade_plans/` | `YYYY-MM-DD_trade_plans.json` |
| `outputs/order_drafts/` | `YYYY-MM-DD_order_drafts.json` |
| `outputs/journal/` | `YYYY-MM-DD_journal.json` |

报告是生成时的快照。当前草稿状态和审批历史以仪表盘读取的 DuckDB 为准。使用自定义数据库时，初始化和日流程传 `--db-path`，CSV 导入传 `--db`；仪表盘及日流程也支持在本地环境中设置 `DATABASE_PATH`。确认各环节指向同一个数据库。

## 5. 在仪表盘审阅

```powershell
..venvScriptspython.exe -m streamlit run apps/dashboard.py --server.address 127.0.0.1
```

浏览器打开 [127.0.0.1:8501](http://127.0.0.1:8501)。端口被占用时加 `--server.port 8502` 并使用对应地址。只允许本机访问，不用公网转发。

| 页面 | 看什么 |
|---|---|
| 每日 CIO 简报 | 当日结论、行情、风险缺口及计划摘要。 |
| 组合持仓 | 指定业务日的持仓、现金和风险快照，注意不同账户与缺失数据。 |
| 交易计划 | 行动、依据、触发与失效条件；可选择查看已被替代的计划。 |
| 订单草稿 | 精确的账户、方向、数量、价格、状态和审批历史。 |
| 投资日志 | 简报、信号、计划、审批备注和导入的成交。 |
| 绩效复盘 | 已入库的周期复盘与逐笔结果；空白表示尚无结果。 |
| 设置 | 只读查看业务时区、账户权限及风控配置。 |

先读计划的失效条件，再打开对应草稿。可以批准、拒绝或延期：批准前核对完整参数并勾选确认；延期后可先恢复待审，再做新的决定。系统会查草稿是否变更，重新核验时效、风控和权限。审批记录和日志同事务保存；新草稿不能沿用旧批准。**在券商端实际执行的交易，要通过真实成交 CSV 回流，不能把「已批准」记成成交。**

## 6. 复盘与常见问题

- **复盘**：先看当时的计划理由和失效条件，再比较实际决策、成交与结果。5、20、60 个交易日的回看和周期复盘目前由[投资日志服务](../investment-journal/README.md)生成，仪表盘只展示已入库结果，日流程不会自动生成这些复盘。计划回看从计划日收盘起算；成交回看从逐笔成交价起算，不等同于已实现净损益。
- **没有草稿**：先看简报里的数据缺口与计划理由。常见是 `WATCH`、Vanguard 个股策略限制、时效或事件门槛、无可交易资金或可卖股数证据。不要靠补假数据或改权限强行生成。
- **简报没有更新**：检查是否尚未收盘或休市，是否使用了正确的数据库，离线模式是否缺行情，以及输出目录是否可写。不要根据之前的报告判断今天已运行。
- **DuckDB 被占用**：等另一个导入、日流程或审批操作结束再重试，不要并发写同一个数据库。备份前先停下写入，再复制数据库到私有目录；恢复时先在副本上核对数据和版本。
- **需要 Schwab API**：先验收真实 CSV、日流程和仪表盘，再看[只读同步部署说明](09_Deployment_Guide.md#18-schwab-api-deployment-notes)。访问令牌仅限本地，过期即停止。保留 `ORDER_SUBMISSION_ENABLED=false`；模拟提交和对账不能用于实际交易。

需要对某个标的做深入分析时，可使用[中文个股复核技能](../SKILL/SKILL.md)。技能负责分析和审阅，不代替导入、审批或券商操作。
