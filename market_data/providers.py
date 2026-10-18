
"""
先物市場データ取得。

大阪先物:
    日付付きの検証済みJSONファイルから取得。
    日時不明のYahoo価格は正式評価に使用しない。

CME:
    yfinanceの1時間足と日足を取得。
"""

import json
import os
from pathlib import Path

import pandas as pd
import yfinance as yf


def _prepare_dataframe(symbol, df):
    if df is None or df.empty:
        raise RuntimeError(
            f"{symbol}: no data returned"
        )

    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)

    return df.sort_index()


def fetch_yfinance(symbol):
    df = yf.download(
        symbol,
        period="5d",
        interval="1h",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return _prepare_dataframe(symbol, df)


def fetch_yfinance_daily(symbol):
    df = yf.download(
        symbol,
        period="10d",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return _prepare_dataframe(symbol, df)


def fetch_yahoo_japan_osaka_futures(
    symbol="5040469.O",
):
    """
    互換性維持用。

    Yahooの時刻のみの価格は取引年月日を
    確定できないため正式評価に使用しない。
    """
    raise RuntimeError(
        "Osaka futures Yahoo source is disabled: "
        "quote date cannot be verified."
    )


def fetch_verified_osaka_futures(
    base_date,
):
    """
    許諾済みの取得元から作成された
    日付付き大阪先物JSONを読み込む。

    環境変数 OSAKA_FUTURES_FILE で
    入力ファイルを指定できる。
    """

    file_path = Path(
        os.getenv(
            "OSAKA_FUTURES_FILE",
            "input/osaka_futures.json",
        )
    )

    if not file_path.is_file():
        raise RuntimeError(
            "Verified Osaka futures input missing: "
            f"{file_path}"
        )

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    required = (
        "symbol",
        "source",
        "trading_date",
        "contract_month",
        "quote_datetime",
        "value",
        "previous_close",
    )

    missing = [
        field
        for field in required
        if data.get(field) is None
    ]

    if missing:
        raise RuntimeError(
            f"Osaka futures missing fields: {missing}"
        )

    if str(data["trading_date"]) != base_date.isoformat():
        raise RuntimeError(
            "Osaka trading date mismatch: "
            f"expected={base_date} "
            f"actual={data['trading_date']}"
        )

    return data
