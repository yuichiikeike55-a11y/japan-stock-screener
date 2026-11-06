
"""
先物市場データの標準化。

CME:
- 07:00 JST以前に確定した直近1時間足を採用
- 前CMEセッションの同時刻の確定1時間足と比較
- 日足清算値は使用しない
- 連続先物の限月一致は未検証として明示
"""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


JST = ZoneInfo("Asia/Tokyo")


def normalize_yfinance(
    symbol,
    hourly_df,
    daily_df=None,
    cutoff=None,
    session_date=None,
    previous_session_end=None,
):
    if hourly_df is None or hourly_df.empty:
        raise RuntimeError(
            f"{symbol}: hourly data missing"
        )

    if "Close" not in hourly_df.columns:
        raise RuntimeError(
            f"{symbol}: hourly Close missing"
        )

    if cutoff is None:
        cutoff = datetime.now(JST)

    if cutoff.tzinfo is None:
        raise RuntimeError(
            "cutoff must be timezone-aware"
        )

    if previous_session_end is None:
        raise RuntimeError(
            "previous_session_end is required"
        )

    if previous_session_end.tzinfo is None:
        raise RuntimeError(
            "previous_session_end must be timezone-aware"
        )

    cutoff = cutoff.astimezone(JST)
    previous_session_end = (
        previous_session_end.astimezone(JST)
    )

    hourly = hourly_df.copy()

    if hourly.index.tz is None:
        raise RuntimeError(
            f"{symbol}: hourly timezone missing"
        )

    hourly.index = hourly.index.tz_convert(JST)
    hourly = hourly.sort_index()
    hourly = hourly.dropna(subset=["Close"])

    if hourly.index.has_duplicates:
        raise RuntimeError(
            f"{symbol}: duplicate hourly timestamps"
        )

    completed_at = (
        hourly.index + pd.Timedelta(hours=1)
    )

    current_bars = hourly.loc[
        completed_at <= cutoff
    ]

    previous_bars = hourly.loc[
        completed_at <= previous_session_end
    ]

    if current_bars.empty or previous_bars.empty:
        raise RuntimeError(
            f"{symbol}: comparison hourly data missing"
        )

    current_start = current_bars.index[-1]
    previous_start = previous_bars.index[-1]

    current_end = current_start + timedelta(hours=1)
    previous_end = previous_start + timedelta(hours=1)

    current_gap = (
        cutoff - current_end
    ).total_seconds() / 60

    previous_gap = (
        previous_session_end - previous_end
    ).total_seconds() / 60

    if not 0 <= current_gap <= 60:
        raise RuntimeError(
            f"{symbol}: current hourly bar not near cutoff"
        )

    if not 0 <= previous_gap <= 60:
        raise RuntimeError(
            f"{symbol}: previous hourly bar not near cutoff"
        )

    if current_end <= previous_end:
        raise RuntimeError(
            f"{symbol}: invalid comparison chronology"
        )

    if (
        current_end.astimezone(JST).time()
        != previous_end.astimezone(JST).time()
    ):
        raise RuntimeError(
            f"{symbol}: comparison time mismatch"
        )

    value = float(current_bars.iloc[-1]["Close"])
    previous_close = float(
        previous_bars.iloc[-1]["Close"]
    )

    if not (
        math.isfinite(value)
        and math.isfinite(previous_close)
        and value > 0
        and previous_close > 0
    ):
        raise RuntimeError(
            f"{symbol}: invalid hourly comparison prices"
        )


    change_pct = (
        (value / previous_close) - 1
    ) * 100

    # 参考データの異常変動を検出する。
    # 5%以上の変動は自動採点に使用しない。
    large_change_detected = abs(change_pct) >= 5.0

    if large_change_detected:
        print(
            "[CME PRICE ANOMALY WARNING]",
            f"change_pct={change_pct:.4f}",
            "manual_review_required=True",
            flush=True,
        )

    print(
        "[CME HOURLY COMPARISON]",
        f"current_end={current_end.isoformat()}",
        f"current_price={value}",
        f"previous_end={previous_end.isoformat()}",
        f"previous_price={previous_close}",
        f"change_pct={change_pct:.4f}",
        flush=True,
    )

    return {
        "symbol": symbol,
        "source": "yfinance",
        "value": value,
        "previous_close": previous_close,
        "change": value - previous_close,
        "change_pct": change_pct,
        "as_of": current_end.isoformat(),
        "bar_start_jst": current_start.isoformat(),
        "bar_completed_jst": current_end.isoformat(),
        "previous_bar_completed_jst": (
            previous_end.isoformat()
        ),
        "price_basis": "completed_hourly_close",
        "contract_month_verified": False,
        "market_data_quality": "reference_only",
    }


def normalize_yahoo_japan_osaka(raw_data, now=None):
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

    if not (
        math.isfinite(value)
        and math.isfinite(previous_close)
        and value > 0
        and previous_close > 0
    ):
        raise RuntimeError(
            "Invalid Osaka futures price"
        )

    return {
        "symbol": raw_data["symbol"],
        "source": raw_data["source"],
        "trading_date": raw_data["trading_date"],
        "contract_month": raw_data["contract_month"],
        "value": value,
        "previous_close": previous_close,
        "change": value - previous_close,
        "change_pct": (
            (value / previous_close) - 1
        ) * 100,
        "as_of": as_of.astimezone(JST).isoformat(),
    }
