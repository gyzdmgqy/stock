# 分析引擎

Phase 4 从 DuckDB 读取指定标的截至指定交易日的已完成行情，计算日线指标，
生成 `DailySignal` 和逐项规则明细，并在同一事务内写入。

## 运行

在仓库根目录启动 Python。数据库须已初始化，目标交易日及历史日线须已通过
[行情服务](../market-data-service/README.md)写入。

```powershell
$env:PYTHONPATH = "analysis-engine/src;market-data-service/src"
.\.venv\Scripts\python.exe
```

```python
from datetime import date

from analysis_engine.services.signal_service import DailySignalService
from shared.db import DEFAULT_DB_PATH, connect_database

with connect_database(DEFAULT_DB_PATH) as db:
    signal = DailySignalService(db).generate_daily_signal("VOO", date(2026, 6, 5))
```

## 指标与规则

- MA5/10/20/30/50/100/200 使用最近完整窗口的收盘价算术平均，包含计算当日。
- ATR14 用真实振幅，RSI14 用每日收盘价变化。两者以首个满 14 项窗口的平均值
  为初值，再用 Wilder 递推。RSI 的收盘价持续不变时为 50。
- 5/20 日成交量均值包含当日。量比以此前 5/20 个交易日的均量为分母。
  窗口不足或分母为零时，量比保留空值。
- MA200 附近范围为 ±1%，包含两个边界。收盘位于 MA200 上方且
  MA20 > MA50 > MA200 时为上行趋势。下行趋势采用对称条件，其余为区间。
  下跌日量比达到 2 时，行情状态优先标为 `HIGH_RISK`。
- 假跌破比较前一交易日已知的 MA200。日线或同日已入库的小时线最低价须跌破
  该水平，当日收盘须回到其上方。下影线至少占全日振幅的 40%，量比须小于 2。
  四项各 20 分，全通过另加 20 分。计算所需数据缺失时，评分保留空值。
- 成交量确认以当日收盘高于前收为前提。成交量超过此前五日均量、超过最近一个
  下跌日成交量，以及收盘进入全日振幅顶部 25%，各占三分之一。没有可用的
  下跌日基准时，不计算上涨日确认总分。
- 跳空百分比为开盘相对前收的变化。绝对值低于 0.5% 归为无显著跳空。
  下跳空后收复前收标为 `SHAKEOUT`，下跳空未收复且量比达到 2 标为
  `PANIC`。其他显著跳空记录方向和幅度。

阈值可通过传入 `SignalRules` 调整。计算使用数据源非自动复权 OHLCV。
公司行动导致的价格跳变需要后续单独处理。Phase 4 统一给出 `WATCH`，
入场、退出、置信度和交易计划属于后续策略层。

## 入库与追溯

`daily_indicator` 按标的和日期存储最新指标。信号 ID 由使用的 OHLCV、
同日小时线最低价和规则版本及参数生成。相同输入重跑复用已有信号，
行情更正或规则参数变化会生成新版本，旧的信号及明细继续可查。
`signal_detail` 记录规则输入说明及得分，布尔判定为 `true`、`false`
或 `null`。指定交易日缺少日线会返回结构化错误。
