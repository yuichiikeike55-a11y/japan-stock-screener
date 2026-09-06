"""
市場データの標準化処理。

1時間足と日足の生DataFrameを、
後続処理で共通して扱える形式へ変換する。

この段階では鮮度判定や
正常・異常の最終判定は行わない。
"""


def normalize_yfinance(
    symbol,
    hourly_df,
    daily_df,
):
    """
    yfinanceの1時間足と日足を
    共通市場データ形式へ変換する。

    value:
        最新1時間足のClose

    previous_close:
        最新1時間足の日付より前にある
        最新の日足Close
    """

    # =====================================
    # 1時間足チェック
    # =====================================

    if (
        hourly_df is None
        or hourly_df.empty
    ):
        raise RuntimeError(
            f"{symbol}: empty hourly DataFrame"
        )

    if "Close" not in hourly_df.columns:
        raise RuntimeError(
            f"{symbol}: hourly Close column is missing"
        )

    valid_hourly = hourly_df.dropna(
        subset=["Close"]
    )

    if valid_hourly.empty:
        raise RuntimeError(
            f"{symbol}: no valid hourly Close data"
        )

    # =====================================
    # 日足チェック
    # =====================================

    if (
        daily_df is None
        or daily_df.empty
    ):
        raise RuntimeError(
            f"{symbol}: empty daily DataFrame"
        )

    if "Close" not in daily_df.columns:
        raise RuntimeError(
            f"{symbol}: daily Close column is missing"
        )

    valid_daily = daily_df.dropna(
        subset=["Close"]
    )

    if valid_daily.empty:
        raise RuntimeError(
            f"{symbol}: no valid daily Close data"
        )

    # =====================================
    # 最新値
    # =====================================

    latest_hourly = valid_hourly.iloc[-1]

    value = float(
        latest_hourly["Close"]
    )

    latest_timestamp = (
        valid_hourly.index[-1]
    )

    latest_date = (
        latest_timestamp.date()
    )

    # =====================================
    # 前営業日終値
    # =====================================

    previous_daily_rows = (
        valid_daily[
            valid_daily.index.map(
                lambda x:
                    x.date()
                    < latest_date
            )
        ]
    )

    if previous_daily_rows.empty:
        raise RuntimeError(
            f"{symbol}: previous daily Close not found"
        )

    previous_daily = (
        previous_daily_rows.iloc[-1]
    )

    previous_close = float(
        previous_daily["Close"]
    )

    if previous_close == 0:
        raise RuntimeError(
            f"{symbol}: previous Close is zero"
        )

    # =====================================
    # 前日比
    # =====================================

    change = (
        value
        - previous_close
    )

    change_pct = (
        change
        / previous_close
        * 100
    )

    # =====================================
    # 最新時刻
    # =====================================

    as_of = (
        latest_timestamp.isoformat()
    )

    # =====================================
    # 共通形式
    # =====================================

    return {
        "symbol":
            symbol,

        "source":
            "yfinance",

        "value":
            value,

        "previous_close":
            previous_close,

        "change":
            change,

        "change_pct":
            change_pct,

        "as_of":
            as_of,
    }