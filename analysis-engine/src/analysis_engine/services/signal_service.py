from datetime import date
from hashlib import sha256
from json import dumps

import pandas as pd
from duckdb import DuckDBPyConnection, Error

from market_data.errors import MarketDataError
from market_data.repositories.daily_price_repository import DailyPriceRepository
from market_data.repositories.intraday_price_repository import IntradayPriceRepository
from shared.enums import Action, ErrorType, SignalComponent
from shared.models import DailyIndicator, DailyPrice, DailySignal

from ..errors import AnalysisError
from ..indicators.moving_average import moving_averages
from ..indicators.volatility import atr, rsi
from ..indicators.volume import volume_indicators
from ..signals.evidence import RuleDetail
from ..signals.false_breakdown import score_false_breakdown
from ..signals.gap_analysis import analyze_gap
from ..signals.market_regime import classify_market, classify_price_location
from ..signals.rules import DEFAULT_RULES, RULE_VERSION, SignalRules
from ..signals.volume_confirmation import score_volume_confirmation
from ._persistence import save_analysis

OHLCV = ("open", "high", "low", "close", "volume")


def _number(value: float) -> float | None:
    return None if pd.isna(value) else float(value)


class DailySignalService:
    def __init__(
        self, db: DuckDBPyConnection, *, rules: SignalRules = DEFAULT_RULES
    ) -> None:
        self._db = db
        self._daily = DailyPriceRepository(db)
        self._intraday = IntradayPriceRepository(db)
        self._rules = rules

    def generate_daily_signal(self, symbol: str, trade_date: date) -> DailySignal:
        try:
            bars = self._daily.get_daily_prices(symbol, date.min, trade_date)
            if not bars or bars[-1].trade_date != trade_date:
                raise AnalysisError(
                    ErrorType.DATA_MISSING,
                    "指定交易日缺少日线",
                    symbol=symbol,
                    trade_date=trade_date,
                )
            candle = bars[-1]
            intraday_low = min(
                (
                    bar.low
                    for bar in self._intraday.get_intraday_prices(
                        candle.symbol, trade_date
                    )
                    if bar.low is not None
                ),
                default=None,
            )
        except MarketDataError as exc:
            raise AnalysisError(
                exc.error_type,
                str(exc),
                symbol=exc.symbol,
                trade_date=trade_date if isinstance(trade_date, date) else None,
            ) from exc

        indicator, signal, details = self._analyze(bars, intraday_low)
        try:
            return save_analysis(self._db, indicator, signal, details)
        except Error as exc:
            raise AnalysisError(
                ErrorType.UNKNOWN,
                "保存日线分析结果失败",
                symbol=candle.symbol,
                trade_date=trade_date,
            ) from exc

    def _analyze(
        self, bars: list[DailyPrice], intraday_low: float | None
    ) -> tuple[DailyIndicator, DailySignal, tuple[RuleDetail, ...]]:
        candle = bars[-1]
        history = [
            (bar.trade_date.isoformat(), *(getattr(bar, field) for field in OHLCV))
            for bar in bars
        ]
        frame = pd.DataFrame(history, columns=("trade_date", *OHLCV))
        if frame.isna().any().any():
            raise AnalysisError(
                ErrorType.VALIDATION_ERROR,
                "历史日线缺少 OHLCV 字段",
                symbol=candle.symbol,
                trade_date=candle.trade_date,
            )

        close = frame["close"]
        averages = moving_averages(close)
        volume = volume_indicators(frame["volume"])
        atr14 = atr(frame["high"], frame["low"], close)
        rsi14 = rsi(close)
        indicator = DailyIndicator(
            symbol=candle.symbol,
            trade_date=candle.trade_date,
            **{name: _number(value) for name, value in averages.iloc[-1].items()},
            **{name: _number(value) for name, value in volume.iloc[-1].items()},
            atr14=_number(atr14.iloc[-1]),
            rsi14=_number(rsi14.iloc[-1]),
        )
        previous_close = _number(close.shift().iloc[-1])
        prior_ma200 = _number(averages["ma200"].shift().iloc[-1])
        prior_volume_avg5 = _number(volume["volume_avg5"].shift().iloc[-1])
        down_day_volume = frame.loc[
            close.diff().lt(0) & (frame.index < len(frame) - 1), "volume"
        ]
        previous_down_volume = (
            None if down_day_volume.empty else int(down_day_volume.iloc[-1])
        )

        location = classify_price_location(
            candle.close, indicator.ma200, rules=self._rules
        )
        regime, trend = classify_market(
            candle.close,
            indicator.ma20,
            indicator.ma50,
            indicator.ma200,
            previous_close=previous_close,
            volume_ratio=indicator.volume_ratio_5,
            rules=self._rules,
        )
        breakdown = score_false_breakdown(
            candle,
            prior_ma200,
            prior_volume_avg5,
            intraday_low=intraday_low,
            rules=self._rules,
        )
        confirmation = score_volume_confirmation(
            candle,
            previous_close=previous_close,
            prior_volume_avg5=prior_volume_avg5,
            previous_down_volume=previous_down_volume,
            rules=self._rules,
        )
        gap_type, gap_direction, gap_percent = analyze_gap(
            candle,
            previous_close=previous_close,
            volume_ratio=indicator.volume_ratio_5,
            rules=self._rules,
        )
        # 版本只取实际参与计算的数据，时间戳和未使用的复权收盘价不影响去重。
        inputs = dumps(
            (RULE_VERSION, self._rules.model_dump(), history, intraday_low),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        version = sha256(inputs.encode()).hexdigest()[:16]
        signal = DailySignal(
            signal_id=f"SIG-{candle.trade_date:%Y%m%d}-{candle.symbol}-{version}",
            symbol=candle.symbol,
            trade_date=candle.trade_date,
            market_regime=regime,
            trend_state=trend,
            price_location=location,
            gap_type=gap_type,
            gap_direction=gap_direction,
            gap_percent=gap_percent,
            false_breakdown_score=breakdown.score,
            volume_confirmation_score=confirmation.score,
            action_hint=Action.WATCH,
            reason=(
                f"行情状态 {regime or '待定'}，价格位置 {location or '待定'}。"
                f"假跌破评分 {_display_score(breakdown.score)}，"
                f"成交量确认评分 {_display_score(confirmation.score)}。"
            ),
        )
        return (
            indicator,
            signal,
            (
                RuleDetail(
                    SignalComponent.TREND,
                    "analysis_rules",
                    dumps({"version": RULE_VERSION, **self._rules.model_dump()}),
                    None,
                    "记录本信号所用规则版本及参数。",
                ),
                RuleDetail(
                    SignalComponent.TREND,
                    "market_regime",
                    dumps(regime),
                    None,
                    f"收盘 {candle.close}，MA20 {indicator.ma20}，MA50 {indicator.ma50}，"
                    f"MA200 {indicator.ma200}，前收 {previous_close}，量比 {indicator.volume_ratio_5}。",
                ),
                RuleDetail(
                    SignalComponent.TREND,
                    "price_vs_ma200",
                    dumps(location),
                    None,
                    f"收盘 {candle.close}，MA200 {indicator.ma200}，"
                    f"附近区间为 ±{self._rules.near_ma200_fraction:.1%}。",
                ),
                RuleDetail(
                    SignalComponent.GAP,
                    "opening_gap",
                    dumps(gap_percent),
                    None,
                    f"开盘 {candle.open}，前收 {previous_close}，方向 {gap_direction}，类型 {gap_type}。",
                ),
                *breakdown.details,
                *confirmation.details,
            ),
        )


def _display_score(score: float | None) -> str:
    return "待定" if score is None else f"{score:.1f}"
