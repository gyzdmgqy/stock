# 市场数据服务

Phase 3 使用 yfinance 下载日线，通过 `DailyPriceProvider` 接口支持替换数据源。
服务将行情规范化为 `DailyPrice`，再按 `(symbol, trade_date)` 批量写入 DuckDB。

## 下载和查询

按仓库根目录的 README 安装依赖并初始化数据库。用 PowerShell 在仓库根目录
启动 Python，确保可以导入 `market_data`。

```powershell
$env:PYTHONPATH = "market-data-service/src"
.\.venv\Scripts\python.exe
```

```python
from datetime import date

from market_data.providers.yfinance_provider import YFinanceProvider
from market_data.repositories.daily_price_repository import DailyPriceRepository
from market_data.services.daily_price_service import DailyPriceService
from shared.db import DEFAULT_DB_PATH, connect_database

start = date(2026, 6, 4)
end = date(2026, 6, 5)
with connect_database(DEFAULT_DB_PATH) as db:
    repository = DailyPriceRepository(db)
    service = DailyPriceService(YFinanceProvider(), repository)
    service.download_daily_prices("VOO", start, end)
    bars = repository.get_daily_prices("VOO", start, end)
    latest = repository.get_latest_daily_price("VOO")
```

起止交易日均计入，日线按交易所日期保存。OHLC 使用数据源关闭自动复权后的值，
复权收盘价单独保存为 `adjusted_close`，缺失时为 `NULL`。
同一主键重复写入时采用本批最后一条记录，并保留已有行的创建时间。

下载无数据时会抛出 `MarketDataError`。调用 `to_message()` 可取得通信协议定义的
结构化错误。查询无匹配历史记录时，区间查询返回空列表，最新日线查询返回 `None`。

小时线仓储支持写入和按交易日读取 `1h` 数据，`bar_start` 使用 UTC。
小时线下载和技术指标属于后续阶段。
