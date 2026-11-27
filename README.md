# Personal CIO System

个人投资决策辅助系统。项目采用本地优先的 Python 单仓库，由行情服务、分析引擎、交易规划、券商网关、CIO 简报和投资日志组成。Phase 11 已提供本地审阅仪表盘；券商数据仍从 CSV 导入，不连接券商 API 或提交订单。

## 本地启动

需要 Python 3.12 或更新版本。在仓库根目录运行。Windows PowerShell 使用以下命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_workspace.py
.\.venv\Scripts\python.exe scripts/init_db.py
.\.venv\Scripts\python.exe -m pytest
```

macOS 和 Linux 使用以下命令。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/init_workspace.py
.venv/bin/python scripts/init_db.py
.venv/bin/python -m pytest
```

初始化脚本可重复执行，会创建本地数据、券商导入、报告、日志和备份目录，保留其中已有文件。基础测试无需 `.env` 或券商凭据。样例配置使用 `America/Chicago`，默认关闭券商 API 同步和订单提交。

数据库默认位于 `data/db/personal_cio.duckdb`。可使用 `init_db.py --db-path <路径>`
指定其他文件。初始化会执行尚未应用的迁移、补齐缺失的种子记录，并保留已有记录。
数据库测试使用临时文件。

收盘后运行 `python scripts/run_daily_pipeline.py`。默认只补齐本地缺失的日线；加 `--offline` 可完全离线。持仓、现金导入及本地人工确认的用法见[每日流程部署说明](docs/09_Deployment_Guide.md#12-daily-local-run)。

运行 `python -m streamlit run apps/dashboard.py --server.address 127.0.0.1`，在 [127.0.0.1:8501](http://127.0.0.1:8501) 查看简报和本地审批。见[仪表盘部署说明](docs/09_Deployment_Guide.md#14-streamlit-dashboard-deployment)。

## 开发约定

实现沟通、新增或修订的文档正文，以及提交消息使用中文。代码标识符沿用英文。提交消息示例为 `chore(repo): 搭建个人 CIO 仓库基础`。

从仓库根目录运行 `python -m black --check .` 和 `python -m ruff check .`。各模块预留源码、测试和配置目录，公共测试与工具配置集中在根目录。

- [仓库引导计划](docs/03_Repository_Bootstrap_Plan.md)
- [部署指南](docs/09_Deployment_Guide.md)
- [开发阶段与 TDD 计划](docs/10_TDD_Development_Plan_and_Codex_Prompts.md)
