"""
市場データの標準化処理。

providerが取得した生DataFrameを、
後続処理で共通して扱える形式へ変換する。

この段階では鮮度判定や
正常・異常の最終判定は行わない。
"""


def normalize_yfinance(
    symbol,
    df,
):
    """
    yfinanceのDataFrameを
    共通市場データ形式へ変換する。
    """

    if df is None or df.empty:
        raise RuntimeError(
            f"{symbol}: empty DataFrame"
        )

    if "Close" not in df.columns:
        raise RuntimeError(
            f"{symbol}: Close column is missing"
        )

    # Closeが有効な行だけを使用する
    valid = df.dropna(
        subset=["Close"]
    )

    if len(valid) < 2:
        raise RuntimeError(
            f"{symbol}: not enough valid Close data"
        )

    latest = valid.iloc[-1]
    previous = valid.iloc[-2]

    value = float(
        latest["Close"]
    )

    previous_close = float(
        previous["Close"]
    )

    if previous_close == 0:
        raise RuntimeError(
            f"{symbol}: previous Close is zero"
        )

    change = (
        value
        - previous_close
    )

    change_pct = (
        change
        / previous_close
        * 100
    )

    as_of = (
        valid.index[-1]
        .isoformat()
    )

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