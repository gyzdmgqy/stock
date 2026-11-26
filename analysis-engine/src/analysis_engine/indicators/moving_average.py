import pandas as pd

MA_WINDOWS = (5, 10, 20, 30, 50, 100, 200)


def moving_averages(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            f"ma{window}": close.rolling(window, min_periods=window).mean()
            for window in MA_WINDOWS
        }
    )
