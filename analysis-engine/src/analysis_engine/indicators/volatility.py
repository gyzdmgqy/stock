import pandas as pd


def _wilder_average(values: pd.Series, period: int) -> pd.Series:
    seed = values.rolling(period, min_periods=period).mean()
    available = seed.notna()
    if not available.any():
        return seed

    # 第一项使用完整窗口的算术平均，之后按 Wilder 递推。
    start = int(available.to_numpy().argmax())
    tail = pd.concat([seed.iloc[start : start + 1], values.iloc[start + 1 :]])
    seed.iloc[start:] = tail.ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    return seed


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    return _wilder_average(true_range, period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.diff()
    gains = _wilder_average(change.clip(lower=0), period)
    losses = _wilder_average(-change.clip(upper=0), period)
    total = gains + losses
    return (100 * gains / total.where(total.gt(0))).mask(total.eq(0), 50.0)
