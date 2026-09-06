"""
市場データの取得処理。

データ取得元ごとの処理をこのファイルにまとめる。

現在:
- yfinance

将来:
- 別のAPI
- Web取得
- その他のデータプロバイダー

などを追加できる構造にする。
"""

import pandas as pd
import yfinance as yf


def fetch_yfinance(symbol):
    """
    yfinanceから市場データを1銘柄取得する。

    この段階では値の鮮度判定や
    正常・異常の最終判定は行わない。
    取得した生データを共通形式で返す。
    """

    ticker = yf.Ticker(symbol)

    df = ticker.history(
        period="5d",
        interval="1m",
        auto_adjust=False,
    )

    if df.empty:
        raise RuntimeError(
            f"{symbol}: yfinance returned no data"
        )

    # 念のため時刻順に並べる
    df = df.sort_index()

    # Closeが存在する行だけ使用
    df = df.dropna(
        subset=["Close"]
    )

    if df.empty:
        raise RuntimeError(
            f"{symbol}: no valid Close data"
        )

    latest = df.iloc[-1]

    value = float(
        latest["Close"]
    )

    as_of = pd.Timestamp(
        df.index[-1]
    )

    # 前日終値を取得するため日足も取得
    daily = ticker.history(
        period="5d",
        interval="1d",
        auto_adjust=False,
    )

    daily = daily.dropna(
        subset=["Close"]
    )

    previous_close = None

    if len(daily) >= 2:
        previous_close = float(
            daily.iloc[-2]["Close"]
        )

    change = None
    change_pct = None

    if (
        previous_close is not None
        and previous_close != 0
    ):
        change = (
            value
            - previous_close
        )

        change_pct = (
            change
            / previous_close
            * 100
        )

    return {
        "symbol": symbol,
        "source": "yfinance",
        "value": value,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change_pct,
        "as_of": as_of.isoformat(),
    }