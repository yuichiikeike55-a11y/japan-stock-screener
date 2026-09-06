"""
市場データの取得処理。

現段階では yfinance から
1シンボルの生データを取得する。
"""

import pandas as pd
import yfinance as yf


def fetch_yfinance(symbol):
    """
    yfinanceから1シンボルの市場データを取得する。

    この段階では鮮度判定や
    正常・異常の最終判定は行わない。
    取得したデータの構造確認を目的とする。
    """

    df = yf.download(
        symbol,
        period="5d",
        interval="1h",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        raise RuntimeError(
            f"{symbol}: no data returned from yfinance"
        )

    # yfinanceのMultiIndex対策
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)

    return df


if __name__ == "__main__":
    symbol = "NIY=F"

    print("=== yfinance fetch test ===")
    print("symbol:", symbol)

    try:
        df = fetch_yfinance(symbol)

        print()
        print("=== columns ===")
        print(df.columns.tolist())

        print()
        print("=== index type ===")
        print(type(df.index))

        print()
        print("=== latest timestamp ===")
        print(df.index[-1])

        print()
        print("=== latest row ===")
        print(df.tail(1))

        print()
        print("=== last 5 rows ===")
        print(df.tail())

    except Exception as e:
        print()
        print("=== ERROR ===")
        print(repr(e))