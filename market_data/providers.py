"""
市場データの取得処理。

yfinanceから
1時間足データと日足データを取得する。

この段階では鮮度判定や
正常・異常の最終判定は行わない。
"""

import pandas as pd
import yfinance as yf


def _prepare_dataframe(
    symbol,
    df,
):
    """
    yfinanceのDataFrameを
    最低限扱いやすい形に整える。
    """

    if df.empty:
        raise RuntimeError(
            f"{symbol}: no data returned from yfinance"
        )

    # yfinanceのMultiIndex対策
    if isinstance(
        df.columns,
        pd.MultiIndex,
    ):
        df.columns = (
            df.columns
            .get_level_values(0)
        )

    df.index = pd.to_datetime(
        df.index
    )

    return df


def fetch_yfinance(symbol):
    """
    yfinanceから1時間足を取得する。

    主に現在値と最新時刻の確認に使用する。
    """

    df = yf.download(
        symbol,
        period="5d",
        interval="1h",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return _prepare_dataframe(
        symbol,
        df,
    )


def fetch_yfinance_daily(symbol):
    """
    yfinanceから日足を取得する。

    前営業日の終値など、
    日次基準値の確認に使用する。
    """

    df = yf.download(
        symbol,
        period="10d",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return _prepare_dataframe(
        symbol,
        df,
    )


if __name__ == "__main__":
    symbol = "NIY=F"

    print("=== Hourly Data ===")

    hourly = fetch_yfinance(
        symbol
    )

    print(
        hourly.tail()
    )

    print()
    print("=== Daily Data ===")

    daily = fetch_yfinance_daily(
        symbol
    )

    print(
        daily.tail()
    )