# CIO 简报

Phase 7 使用确定性模板生成每日 CIO 简报，同时写入 DuckDB、Markdown 和 JSON。不依赖 LLM，不审批或提交订单。

## 本地调用

先按部署说明初始化数据库。在仓库根目录运行：

```powershell
$env:PYTHONPATH = "personal-cio-agent/src"
.\.venv\Scripts\python.exe
```

在 Python 中指定按 `America/Chicago` 确定的业务日期：

```python
from datetime import date

from personal_cio_agent.services.brief_service import BriefService
from shared.db import DEFAULT_DB_PATH, connect_database

with connect_database(DEFAULT_DB_PATH) as db:
    brief = BriefService(db).generate_daily_brief(date(2026, 6, 5))
    print(brief.markdown_path)
```

## 取数与重跑

- 市场以当日 SPY 日线信号作为代理，附上可用的 QQQ 信号。不会借用前一日的信号或快照。缺失的数值在 JSON 中为 `null`，在 Markdown 中显示为待补齐。
- 组合净值优先用当日组合风险快照；没有汇总值时，仅在全部启用账户都有当日美元净值快照的情况下求和。风险栏引用已有评分和说明，不据此自动推断风险等级。
- 每个账户和标的只展示当日最新计划及其关联草稿。日志提醒最多取五条往日记录，跳过简报生成的日志。
- 默认导出到 `outputs/briefs/YYYY-MM-DD_Daily_CIO_Brief.md` 及同名 `.json` 文件。同日重跑更新同一简报，保留 ID 和创建时间。
- 数据库是主记录。两份文件分别替换，若数据库提交后导出中断，重跑同一日期即可刷新两份导出。
