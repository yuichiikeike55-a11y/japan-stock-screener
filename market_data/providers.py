"""
市場データの取得処理。

yfinanceから
1時間足データと日足データを取得する。

この段階では鮮度判定や
正常・異常の最終判定は行わない。
"""

import re
import time

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

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

def fetch_yahoo_japan_osaka_futures(
    symbol="5040469.O",
):
    """
    Yahoo!ファイナンス日本から
    大阪の日経平均先物1限月を取得する。
    """

    url = (
        "https://finance.yahoo.co.jp/quote/"
        f"{symbol}"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    response = None

    for attempt in range(1, 4):
        print(
            f"{symbol}: HTTP attempt "
            f"{attempt}/3"
        )

        response = requests.get(
            url,
            headers=headers,
            timeout=20,
        )

        print(
            f"{symbol}: HTTP status "
            f"{response.status_code}"
        )

        if response.status_code == 200:
            break

        if attempt < 3:
            time.sleep(5)

    if response is None:
        raise RuntimeError(
            f"{symbol}: no HTTP response"
        )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    if symbol not in text:
        raise RuntimeError(
            f"{symbol}: symbol not found"
        )

    if "日経平均先物1限月" not in text:
        raise RuntimeError(
            f"{symbol}: futures name not found"
        )

    quote_match = re.search(
        r"([0-9,]+\.\d+)\s+"
        r"前日比\s+"
        r"([+-]?[0-9,]+\.\d+)\s+"
        r"\(\s*([+-]?[0-9.]+)\s*%\s*\)\s+"
        r"15分ディレイ株価\s+"
        r"(\d{1,2}:\d{2})",
        text,
    )

    detail_match = re.search(
        r"前日終値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*([0-9]{1,2}/[0-9]{1,2})\s*\)\s+"
        r"始値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"高値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"安値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"出来高\s+用語\s+"
        r"([0-9,]+)\s+株",
        text,
    )

    if quote_match is None:
        raise RuntimeError(
            f"{symbol}: current quote parse failed"
        )

    if detail_match is None:
        raise RuntimeError(
            f"{symbol}: OHLCV parse failed"
        )

    return {
        "symbol": symbol,
        "source": "yahoo_japan",
        "value": float(
            quote_match.group(1).replace(",", "")
        ),
        "change": float(
            quote_match.group(2).replace(",", "")
        ),
        "change_pct": float(
            quote_match.group(3)
        ),
        "quote_time": quote_match.group(4),
        "previous_close": float(
            detail_match.group(1).replace(",", "")
        ),
        "previous_close_date":
            detail_match.group(2),
        "open": float(
            detail_match.group(3).replace(",", "")
        ),
        "high": float(
            detail_match.group(4).replace(",", "")
        ),
        "low": float(
            detail_match.group(5).replace(",", "")
        ),
        "volume": int(
            detail_match.group(6).replace(",", "")
        ),
    }
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
