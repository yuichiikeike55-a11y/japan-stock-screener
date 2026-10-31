
"""
先物市場データの標準化。
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
        raise RuntimeError(f"{symbol}: hourly data missing")

    if daily_df is None or daily_df.empty:
        raise RuntimeError(f"{symbol}: daily data missing")

    if "Close" not in hourly_df.columns:
        raise RuntimeError(f"{symbol}: hourly Close missing")

    if "Close" not in daily_df.columns:
        raise RuntimeError(f"{symbol}: daily Close missing")

    hourly = hourly_df.dropna(subset=["Close"]).copy()
    daily = daily_df.dropna(subset=["Close"]).copy()

    if hourly.empty or daily.empty:
        raise RuntimeError(f"{symbol}: no valid prices")

    if cutoff is None:
        cutoff = datetime.now(JST)

    if cutoff.tzinfo is None:
        raise RuntimeError("cutoff must be timezone-aware")

    cutoff = cutoff.astimezone(JST)

    if hourly.index.tz is None:
        raise RuntimeError(
            f"{symbol}: hourly timestamps have no timezone"
        )

    hourly = hourly.sort_index()
    hourly.index = hourly.index.tz_convert(JST)

    # 1時間足は開始時刻でラベル付けされる前提。
    # 確定時刻が評価上限以内の足だけ採用。
    completed_at = (
        hourly.index + pd.Timedelta(hours=1)
    )

    hourly = hourly.loc[completed_at <= cutoff]

    if hourly.empty:
        raise RuntimeError(
            f"{symbol}: no completed hourly bar"
        )

    latest_start = hourly.index[-1]
    latest_end = latest_start + timedelta(hours=1)

    value = float(hourly.iloc[-1]["Close"])

    # 日足は取引所タイムゾーンの日付ラベルを維持。
    daily = daily.sort_index()

    latest_market_date = latest_start.astimezone(
        daily.index.tz
    ).date() if daily.index.tz is not None else latest_start.date()

    # --------------------------------------------------------
    # CME日時診断ログ
    # --------------------------------------------------------
    print(
        "[CME DATE CHECK]",
        f"symbol={symbol}",
        f"hourly_timezone={hourly.index.tz}",
        f"daily_timezone={daily.index.tz}",
        f"latest_bar_start_jst={latest_start.isoformat()}",
        f"latest_bar_completed_jst={latest_end.isoformat()}",
        f"latest_market_date={latest_market_date}",
        f"evaluation_cutoff_jst={cutoff.isoformat()}",
        flush=True,
    )    
    # --------------------------------------------------------
    # CME日足の日付ラベルを診断
    # 日付の意味が未確認のため、正式評価にはまだ使用しない
    # --------------------------------------------------------
    print(
        "[CME DAILY CHECK]",
        f"symbol={symbol}",
        f"daily_last_dates={[str(x) for x in daily.index[-5:]]}",
        f"hourly_last_start_jst={latest_start.isoformat()}",
        f"hourly_last_end_jst={latest_end.isoformat()}",
        flush=True,
    )
    previous_rows = daily.loc[
        [
            timestamp.date() < latest_market_date
            for timestamp in daily.index
        ]
    ]

    if previous_rows.empty:
        raise RuntimeError(
            f"{symbol}: previous daily Close missing"
        )

    previous_close = float(
        previous_rows.iloc[-1]["Close"]
    )
    print(
        "[CME PREVIOUS CLOSE CHECK]",
        f"symbol={symbol}",
        f"selected_previous_date={previous_rows.index[-1]}",
        f"selected_previous_close={previous_close}",
        f"latest_daily_date={daily.index[-1]}",
        f"latest_daily_close={daily.iloc[-1]['Close']}",
        flush=True,
    )
    if previous_close <= 0:
        raise RuntimeError(
            f"{symbol}: invalid previous Close"
        )

    return {
        "symbol": symbol,
        "source": "yfinance",
        "value": value,
        "previous_close": previous_close,
        "change": value - previous_close,
        "change_pct": (
            (value - previous_close)
            / previous_close
            * 100
        ),
        "as_of": latest_end.isoformat(),
        "bar_start_jst": latest_start.isoformat(),
        "bar_completed_jst": latest_end.isoformat(),
    }


def normalize_yahoo_japan_osaka(
    raw_data,
    now=None,
):
    """
    互換性維持用。
    quote_datetimeが確認できる場合のみ使用。
    """
    return normalize_verified_osaka(raw_data)


def normalize_verified_osaka(raw_data):
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
        key for key in required
        if raw_data.get(key) is None
    ]

    if missing:
        raise RuntimeError(
            f"Osaka missing fields: {missing}"
        )

    as_of = datetime.fromisoformat(
        raw_data["quote_datetime"]
    )

    if as_of.tzinfo is None:
        raise RuntimeError(
            "Osaka quote_datetime must include timezone"
        )

    value = float(raw_data["value"])
    previous_close = float(raw_data["previous_close"])

    if value <= 0 or previous_close <= 0:
        raise RuntimeError("Invalid Osaka futures price")

    return {
        "symbol": raw_data["symbol"],
        "source": raw_data["source"],
        "trading_date": raw_data["trading_date"],
        "contract_month": raw_data["contract_month"],
        "value": value,
        "previous_close": previous_close,
        "change": value - previous_close,
        "change_pct": (
            (value - previous_close)
            / previous_close
            * 100
        ),
        "as_of": as_of.astimezone(JST).isoformat(),
    }
