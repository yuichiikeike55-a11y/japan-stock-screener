
"""
市場データの標準化処理。

CME:
    評価時刻以前の確定済み1時間足を使用する。

大阪:
    取得元に現在値の年月日がない場合、
    日付を推測せず停止する。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


JST = ZoneInfo("Asia/Tokyo")


def normalize_yfinance(
    symbol,
    hourly_df,
    daily_df,
    cutoff=None,
):
    if hourly_df is None or hourly_df.empty:
        raise RuntimeError(f"{symbol}: empty hourly data")

    if daily_df is None or daily_df.empty:
        raise RuntimeError(f"{symbol}: empty daily data")

    if "Close" not in hourly_df.columns:
        raise RuntimeError(f"{symbol}: hourly Close missing")

    if "Close" not in daily_df.columns:
        raise RuntimeError(f"{symbol}: daily Close missing")

    hourly = hourly_df.dropna(subset=["Close"]).copy()
    daily = daily_df.dropna(subset=["Close"]).copy()

    if hourly.empty or daily.empty:
        raise RuntimeError(f"{symbol}: no valid Close data")

    if cutoff is None:
        cutoff = datetime.now(JST)

    if cutoff.tzinfo is None:
        raise RuntimeError("cutoff must include timezone")

    cutoff = cutoff.astimezone(JST)

    if hourly.index.tz is None:
        raise RuntimeError(
            f"{symbol}: hourly index must include timezone"
        )

    hourly = hourly.sort_index()
    hourly.index = hourly.index.tz_convert(JST)

    # yfinanceの1時間足は通常、足の開始時刻。
    # 1時間後に確定した足のみ使用する。
    completed_at = hourly.index + pd.Timedelta(hours=1)

    hourly = hourly.loc[completed_at <= cutoff]

    if hourly.empty:
        raise RuntimeError(
            f"{symbol}: no completed hourly bar before cutoff"
        )

    latest_timestamp = hourly.index[-1]
    latest_completed_at = latest_timestamp + timedelta(hours=1)

    value = float(hourly.iloc[-1]["Close"])

    daily = daily.sort_index()

    # 日足の取引日ラベルは取得元の仕様に依存する。
    # JSTに変換して日付を決め打ちしない。
    latest_date = latest_timestamp.date()

    previous_rows = daily.loc[
        [timestamp.date() < latest_date for timestamp in daily.index]
    ]

    if previous_rows.empty:
        raise RuntimeError(
            f"{symbol}: previous daily Close not found"
        )

    previous_close = float(previous_rows.iloc[-1]["Close"])

    if previous_close == 0:
        raise RuntimeError(f"{symbol}: previous Close is zero")

    change = value - previous_close

    return {
        "symbol": symbol,
        "source": "yfinance",
        "value": value,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change / previous_close * 100,
        "as_of": latest_completed_at.isoformat(),
        "bar_start_jst": latest_timestamp.isoformat(),
        "bar_completed_jst": latest_completed_at.isoformat(),
    }


def normalize_yahoo_japan_osaka(
    raw_data,
    now=None,
):
    required = [
        "symbol",
        "source",
        "value",
        "previous_close",
        "change",
        "change_pct",
        "quote_time",
    ]

    missing = [
        key for key in required
        if raw_data.get(key) is None
    ]

    if missing:
        raise RuntimeError(
            f"Osaka futures missing fields: {missing}"
        )

    # quote_timeだけでは取引日を確定できない。
    # 取得元に明示的な日時がない限り使用しない。
    quote_datetime = raw_data.get("quote_datetime")

    if not quote_datetime:
        raise RuntimeError(
            "Osaka futures quote date is unverified. "
            "A dated quote source is required."
        )

    as_of = datetime.fromisoformat(quote_datetime)

    if as_of.tzinfo is None:
        raise RuntimeError(
            "Osaka quote_datetime must include timezone"
        )

    return {
        "symbol": raw_data["symbol"],
        "source": raw_data["source"],
        "value": float(raw_data["value"]),
        "previous_close": float(raw_data["previous_close"]),
        "change": float(raw_data["change"]),
        "change_pct": float(raw_data["change_pct"]),
        "as_of": as_of.astimezone(JST).isoformat(),
    }
