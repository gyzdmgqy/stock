from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby

import exchange_calendars
from duckdb import DuckDBPyConnection

from analysis_engine.errors import AnalysisError
from analysis_engine.services.signal_service import OHLCV, DailySignalService
from market_data.errors import MarketDataError
from market_data.providers import DailyPriceProvider
from market_data.repositories.daily_price_repository import DailyPriceRepository
from market_data.services.daily_price_service import DailyPriceService
from shared.models import DailySignal
from trade_planner.rules.hourly_gate import APP_TIMEZONE


@dataclass(frozen=True)
class SessionWindow:
    day: date
    history: tuple[date, ...]
    sessions: tuple[date, ...]
    current_hours: tuple[datetime, datetime]
    previous_hours: tuple[datetime, datetime]


def session_window(
    as_of: datetime, history_count: int, future_count: int
) -> tuple[SessionWindow | None, str | None]:
    day = as_of.astimezone(APP_TIMEZONE).date()
    start = day - timedelta(days=history_count * 2)
    end = day + timedelta(days=max(30, future_count * 3))
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=end)
    if not calendar.is_session(day):
        return None, "非交易日，未运行每日流程。"

    def hours(session: date) -> tuple[datetime, datetime]:
        return (
            calendar.session_open(session).to_pydatetime(),
            calendar.session_close(session).to_pydatetime(),
        )

    today = hours(day)
    if as_of < today[1]:
        return None, "交易日尚未收盘，未读取未完成的日线。"
    past = tuple(
        session.date()
        for session in calendar.sessions_in_range(calendar.first_session, day)
    )
    future = tuple(
        session.date()
        for session in calendar.sessions_in_range(day, calendar.last_session)
    )[1:]
    if len(past) <= history_count or len(future) < future_count:
        raise ValueError("交易日历未覆盖完整的行情或事件窗口。")
    history = past[-(history_count + 1) :]
    return (
        SessionWindow(
            day, history, (*history, *future[:future_count]), today, hours(history[-2])
        ),
        None,
    )


class MarketInputs:
    def __init__(
        self,
        db: DuckDBPyConnection,
        window: SessionWindow,
        provider: DailyPriceProvider | None,
    ) -> None:
        self._window = window
        self._prices = DailyPriceRepository(db)
        self._download = (
            DailyPriceService(provider, self._prices) if provider is not None else None
        )
        self._analysis = DailySignalService(db)

    def analyze(self, symbol: str) -> tuple[DailySignal | None, bool, list[str]]:
        window = self._window
        warnings = []
        try:
            present = self._complete_sessions(symbol)
            if self._download is not None and len(present) < len(window.history):
                for missing, group in groupby(
                    window.history, key=lambda day: day not in present
                ):
                    if missing:
                        gap = tuple(group)
                        try:
                            self._download.download_daily_prices(
                                symbol, gap[0], gap[-1]
                            )
                        except MarketDataError as exc:
                            warnings.append(
                                f"{symbol}：补行情失败（{exc.error_type.value}：{exc}）。"
                            )
                present = self._complete_sessions(symbol)

            if window.day not in present:
                warnings.append(f"{symbol}：缺少当日完整日线，不使用旧信号替代。")
                return None, False, warnings
            usable = tuple(day for day in window.history[1:] if day in present)
            missing_count = len(window.history) - len(present)
            complete = missing_count == 0
            if complete:
                # 首次运行也需要前一交易日的 MA200，供连续两日退出规则复核。
                self._analysis.generate_daily_signal(
                    symbol,
                    window.history[-2],
                    history_sessions=window.history[:-1],
                    intraday_session=window.previous_hours,
                )
            else:
                warnings.append(
                    f"{symbol}：行情窗口缺少 {missing_count} 个交易日，仅生成信号，不生成计划或草稿。"
                )
            signal = self._analysis.generate_daily_signal(
                symbol,
                window.day,
                history_sessions=usable,
                intraday_session=window.current_hours,
            )
            return signal, complete, warnings
        except (AnalysisError, MarketDataError) as exc:
            warnings.append(
                f"{symbol}：无法完成日线分析（{exc.error_type.value}：{exc}）。"
            )
            return None, False, warnings

    def _complete_sessions(self, symbol: str) -> set[date]:
        sessions = set(self._window.history)
        return {
            bar.trade_date
            for bar in self._prices.get_daily_prices(
                symbol, self._window.history[0], self._window.day
            )
            if bar.trade_date in sessions
            and all(getattr(bar, name) is not None for name in OHLCV)
        }
