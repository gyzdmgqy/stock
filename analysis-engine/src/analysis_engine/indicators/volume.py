import pandas as pd


def volume_indicators(volume: pd.Series) -> pd.DataFrame:
    result = pd.DataFrame(index=volume.index)
    for window in (5, 20):
        average = volume.rolling(window, min_periods=window).mean()
        prior_average = average.shift(1)
        result[f"volume_avg{window}"] = average
        result[f"volume_ratio_{window}"] = volume / prior_average.where(
            prior_average.gt(0)
        )
    return result
