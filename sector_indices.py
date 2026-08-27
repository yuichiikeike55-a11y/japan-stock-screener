from pathlib import Path
from datetime import datetime, timezone
import json
import math

import os
import numpy as np
import pandas as pd
import yfinance as yf


OUTPUT_DIR = Path("output")
HISTORY_DIR = OUTPUT_DIR / "sector_history"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

HISTORY_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# =========================================================
# セクター分析用
# TOPIX-17連動ETFを基本代理指数として使用
# 半導体は2644を追加
# =========================================================

SECTORS = [
    {
        "sector": "食品",
        "symbol": "1617.T",
        "name": "NEXT FUNDS 食品(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "エネルギー資源",
        "symbol": "1618.T",
        "name": "NEXT FUNDS エネルギー資源(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "建設・資材",
        "symbol": "1619.T",
        "name": "NEXT FUNDS 建設・資材(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "素材・化学",
        "symbol": "1620.T",
        "name": "NEXT FUNDS 素材・化学(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "医薬品",
        "symbol": "1621.T",
        "name": "NEXT FUNDS 医薬品(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "自動車・輸送機",
        "symbol": "1622.T",
        "name": "NEXT FUNDS 自動車・輸送機(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "鉄鋼・非鉄",
        "symbol": "1623.T",
        "name": "NEXT FUNDS 鉄鋼・非鉄(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "機械",
        "symbol": "1624.T",
        "name": "NEXT FUNDS 機械(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "電機・精密",
        "symbol": "1625.T",
        "name": "NEXT FUNDS 電機・精密(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "情報通信・サービスその他",
        "symbol": "1626.T",
        "name": "NEXT FUNDS 情報通信・サービスその他(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "電力・ガス",
        "symbol": "1627.T",
        "name": "NEXT FUNDS 電力・ガス(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "運輸・物流",
        "symbol": "1628.T",
        "name": "NEXT FUNDS 運輸・物流(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "商社・卸売",
        "symbol": "1629.T",
        "name": "NEXT FUNDS 商社・卸売(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "小売",
        "symbol": "1630.T",
        "name": "NEXT FUNDS 小売(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "銀行",
        "symbol": "1631.T",
        "name": "NEXT FUNDS 銀行(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "金融",
        "symbol": "1632.T",
        "name": "NEXT FUNDS 金融(除く銀行)(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "不動産",
        "symbol": "1633.T",
        "name": "NEXT FUNDS 不動産(TOPIX-17)ETF",
        "proxy_type": "ETF",
    },
    {
        "sector": "半導体",
        "symbol": "2644.T",
        "name": "Global X 半導体関連-日本株式 ETF",
        "proxy_type": "ETF",
    },
]


def safe_float(value):
    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(value):
        return None

    return value


def calc_rsi(close, period=14):
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi


def validate_ohlcv(df, symbol):
    """
    OHLCVの明らかな異常値を検出・除外する。
    異常値をMA・RSI・高安値計算へ混入させない。
    """
    x = df.copy()
    flags = []

    price_cols = [
        "Open",
        "High",
        "Low",
        "Close",
    ]

    # 1. 価格が0以下、infなど
    for col in price_cols:
        bad = (
            ~np.isfinite(x[col])
            | (x[col] <= 0)
        )

        if bad.any():
            flags.append(
                f"{col.lower()}_non_positive_or_invalid"
            )

            x.loc[
                bad,
                price_cols
            ] = np.nan

    # 2. OHLCの論理矛盾
    bad_ohlc = (
        (x["High"] < x["Low"])
        | (x["High"] < x["Open"])
        | (x["High"] < x["Close"])
        | (x["Low"] > x["Open"])
        | (x["Low"] > x["Close"])
    )

    if bad_ohlc.any():
        flags.append(
            "ohlc_inconsistency"
        )

        x.loc[
            bad_ohlc,
            price_cols
        ] = np.nan

    # 3. 前日比±40%以上を検出
    close_ratio = (
        x["Close"]
        / x["Close"].shift(1)
    )

    extreme_move = (
        (close_ratio > 1.40)
        | (close_ratio < 0.60)
    )

    if extreme_move.any():
        flags.append(
            "extreme_daily_price_move_detected"
        )

    # 4. 周辺価格から極端に離れた単発値
    rolling_median = (
        x["Close"]
        .rolling(
            21,
            center=True,
            min_periods=5,
        )
        .median()
    )

    for col in price_cols:
        ratio = (
            x[col]
            / rolling_median
        )

        bad_outlier = (
            (ratio < 0.20)
            | (ratio > 5.00)
        )

        if bad_outlier.any():
            flags.append(
                f"{col.lower()}_extreme_outlier"
            )

            x.loc[
                bad_outlier,
                col
            ] = np.nan

    # 5. 出来高の異常
    bad_volume = (
        ~np.isfinite(x["Volume"])
        | (x["Volume"] < 0)
    )

    if bad_volume.any():
        flags.append(
            "invalid_volume"
        )

        x.loc[
            bad_volume,
            "Volume"
        ] = np.nan

    # Closeが無効になった行は除外
    x = x.dropna(
        subset=["Close"]
    )

    # 警告の重複を削除
    flags = list(
        dict.fromkeys(flags)
    )

    return x, flags
def download_history(symbol):
    df = yf.download(
        symbol,
        period="2y",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        return pd.DataFrame()

    # yfinance MultiIndex対策
    if isinstance(
        df.columns,
        pd.MultiIndex,
    ):
        df.columns = (
            df.columns
            .get_level_values(0)
        )

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    missing = [
        col
        for col in required
        if col not in df.columns
    ]

    if missing:
        raise ValueError(
            f"{symbol}: missing columns "
            f"{missing}"
        )

    df = df[required].copy()

    df = df.dropna(
        subset=["Close"]
    )

    df.index = pd.to_datetime(
        df.index
    )

    # OHLCV異常値チェック
    df, quality_flags = validate_ohlcv(
        df,
        symbol,
    )

    # build_latest_recordへ警告を渡す
    df.attrs[
        "data_quality_flags"
    ] = quality_flags

    return df
def calculate_metrics(df):
    x = df.copy()

    close = x["Close"]
    high = x["High"]
    low = x["Low"]
    volume = x["Volume"]

    x["ma5"] = close.rolling(
        5
    ).mean()

    x["ma25"] = close.rolling(
        25
    ).mean()

    x["ma75"] = close.rolling(
        75
    ).mean()

    x["rsi14"] = calc_rsi(
        close,
        14,
    )

    x["high20"] = high.rolling(
        20
    ).max()

    x["low20"] = low.rolling(
        20
    ).min()

    x["high52"] = high.rolling(
        252
    ).max()

    x["low52"] = low.rolling(
        252
    ).min()

    x["avg_volume_5d"] = (
        volume.rolling(5).mean()
    )

    x["avg_volume_20d"] = (
        volume.rolling(20).mean()
    )

    return x


def build_latest_record(
    sector_info,
    df,
):
    x = calculate_metrics(df)
    quality_flags = list(
        df.attrs.get(
            "data_quality_flags",
            []
        )
    )

    if len(x) < 75:
        raise ValueError(
            f"{sector_info['symbol']}: "
            "not enough history"
        )

    current = x.iloc[-1]
    previous = x.iloc[-2]

    close = safe_float(
        current["Close"]
    )

    previous_close = safe_float(
        previous["Close"]
    )

    ma5 = safe_float(
        current["ma5"]
    )

    ma25 = safe_float(
        current["ma25"]
    )

    ma75 = safe_float(
        current["ma75"]
    )

    ma25_previous = safe_float(
        previous["ma25"]
    )

    rsi14 = safe_float(
        current["rsi14"]
    )

    high20 = safe_float(
        current["high20"]
    )

    low20 = safe_float(
        current["low20"]
    )

    high52 = safe_float(
        current["high52"]
    )

    low52 = safe_float(
        current["low52"]
    )
    # =========================================
    # 52週高値・安値の異常値チェック
    # =========================================

    if (
        close is not None
        and high52 is not None
    ):
        if high52 < close:
            quality_flags.append(
                "invalid_high52_below_close"
            )
            high52 = None

    if (
        close is not None
        and low52 is not None
    ):
        if low52 > close:
            quality_flags.append(
                "invalid_low52_above_close"
            )
            low52 = None

        elif low52 < close * 0.10:
            quality_flags.append(
                "invalid_low52_extreme_outlier"
            )
            low52 = None

    # 警告の重複を削除
    quality_flags = list(
        dict.fromkeys(
            quality_flags
        )
    )

    volume = safe_float(
        current["Volume"]
    )

    avg_volume_5d = safe_float(
        current["avg_volume_5d"]
    )

    avg_volume_20d = safe_float(
        current["avg_volume_20d"]
    )

    ma25_slope = None

    if (
        ma25 is not None
        and ma25_previous is not None
    ):
        ma25_slope = (
            ma25
            - ma25_previous
        )

    ma25_direction = None

    if ma25_slope is not None:
        if ma25_slope > 0:
            ma25_direction = "up"
        elif ma25_slope < 0:
            ma25_direction = "down"
        else:
            ma25_direction = "flat"

    def gap_pct(
        value,
        base,
    ):
        if (
            value is None
            or base is None
            or base == 0
        ):
            return None

        return (
            value / base - 1
        ) * 100

    return_1d = gap_pct(
        close,
        previous_close,
    )

    return_5d = None

    if len(x) >= 6:
        return_5d = gap_pct(
            close,
            safe_float(
                x.iloc[-6]["Close"]
            ),
        )

    return_20d = None

    if len(x) >= 21:
        return_20d = gap_pct(
            close,
            safe_float(
                x.iloc[-21]["Close"]
            ),
        )

    volume_ratio_20d = None

    if (
        volume is not None
        and avg_volume_20d
        not in (None, 0)
    ):
        volume_ratio_20d = (
            volume
            / avg_volume_20d
        )

    base_date = (
        x.index[-1]
        .strftime("%Y-%m-%d")
    )

    return {
        "sector": sector_info[
            "sector"
        ],
        "symbol": sector_info[
            "symbol"
        ],
        "name": sector_info[
            "name"
        ],
        "proxy_type": sector_info[
            "proxy_type"
        ],
        "source": "yfinance",
        "base_date": base_date,
        "data_quality_status":
            "warning"
            if quality_flags
            else "ok",

        "data_quality_flags":
            quality_flags,    

        "open": safe_float(
            current["Open"]
        ),
        "high": safe_float(
            current["High"]
        ),
        "low": safe_float(
            current["Low"]
        ),
        "close": close,
        "volume": volume,

        "ma5": ma5,
        "ma25": ma25,
        "ma75": ma75,

        "ma25_previous":
            ma25_previous,
        "ma25_slope":
            safe_float(
                ma25_slope
            ),
        "ma25_direction":
            ma25_direction,

        "ma5_gap_pct":
            safe_float(
                gap_pct(
                    close,
                    ma5,
                )
            ),

        "ma25_gap_pct":
            safe_float(
                gap_pct(
                    close,
                    ma25,
                )
            ),

        "ma75_gap_pct":
            safe_float(
                gap_pct(
                    close,
                    ma75,
                )
            ),

        "rsi14": rsi14,

        "high20": high20,
        "low20": low20,
        "high52": high52,
        "low52": low52,

        "high20_gap_pct":
            safe_float(
                gap_pct(
                    close,
                    high20,
                )
            ),

        "high52_gap_pct":
            safe_float(
                gap_pct(
                    close,
                    high52,
                )
            ),

        "return_1d_pct":
            safe_float(
                return_1d
            ),

        "return_5d_pct":
            safe_float(
                return_5d
            ),

        "return_20d_pct":
            safe_float(
                return_20d
            ),

        "avg_volume_5d":
            avg_volume_5d,

        "avg_volume_20d":
            avg_volume_20d,

        "volume_ratio_20d":
            safe_float(
                volume_ratio_20d
            ),
    }


def build_history_records(df):
    records = []

    # 最新300営業日を保存
    history = df.tail(
        300
    )

    for index, row in (
        history.iterrows()
    ):
        records.append(
            {
                "date":
                    index.strftime(
                        "%Y-%m-%d"
                    ),
                "open":
                    safe_float(
                        row["Open"]
                    ),
                "high":
                    safe_float(
                        row["High"]
                    ),
                "low":
                    safe_float(
                        row["Low"]
                    ),
                "close":
                    safe_float(
                        row["Close"]
                    ),
                "volume":
                    safe_float(
                        row["Volume"]
                    ),
            }
        )

    return records


def main():
    requested_base_date_raw = os.environ.get(
        "BASE_DATE",
        "",
    ).strip()

    requested_base_date = None

    if requested_base_date_raw:
        requested_base_date = pd.Timestamp(
            requested_base_date_raw
        ).normalize()
    latest_results = []
    failures = []

    for item in SECTORS:
        symbol = item["symbol"]

        try:
            print(
                "Downloading:",
                symbol,
                item["sector"],
            )

            df = download_history(
                symbol
            )

            if df.empty:
                raise RuntimeError(
                    f"{symbol}: no data"
                )
            # BASE_DATEが指定されている場合、
            # yfinanceの最新日が要求日と一致することを必須にする
            if requested_base_date is not None:
                actual_base_date = (
                    pd.Timestamp(
                        df.index[-1]
                    )
                    .tz_localize(None)
                    .normalize()
                )

                if actual_base_date != requested_base_date:
                    raise RuntimeError(
                        f"{symbol}: requested base date "
                        f"{requested_base_date.date()} "
                        f"is not ready. "
                        f"Latest available date is "
                        f"{actual_base_date.date()}."
                    )
            latest = (
                build_latest_record(
                    item,
                    df,
                )
            )

            latest_results.append(
                latest
            )

            history_json = {
                "sector":
                    item["sector"],
                "symbol":
                    symbol,
                "name":
                    item["name"],
                "proxy_type":
                    item["proxy_type"],
                "source":
                    "yfinance",
                "base_date":
                    latest[
                        "base_date"
                    ],
                "generated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                "history":
                    build_history_records(
                        df
                    ),
            }

            filename = (
                symbol
                .replace(
                    ".",
                    "_"
                )
                + ".json"
            )

            with open(
                HISTORY_DIR
                / filename,
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    history_json,
                    f,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )

        except Exception as e:
            print(
                "FAILED:",
                symbol,
                repr(e),
            )

            failures.append(
                {
                    "sector":
                        item[
                            "sector"
                        ],
                    "symbol":
                        symbol,
                    "error":
                        str(e),
                }
            )
    # =========================================
    # BASE_DATE 最終整合性チェック
    # 18セクターすべてが指定日に揃っていなければ
    # latest JSONを公開しない
    # =========================================
    if requested_base_date is not None:
        expected_date = requested_base_date.strftime(
            "%Y-%m-%d"
        )

        wrong_dates = [
            x
            for x in latest_results
            if x["base_date"] != expected_date
        ]

        if (
            failures
            or wrong_dates
            or len(latest_results) != len(SECTORS)
        ):
            raise RuntimeError(
                f"Sector data for {expected_date} is not ready. "
                f"processed={len(latest_results)}/{len(SECTORS)}, "
                f"failures={len(failures)}, "
                f"wrong_dates={len(wrong_dates)}. "
                f"Previous trading day will NOT be published."
            )      
    base_dates = [
        x["base_date"]
        for x in latest_results
    ]

    latest_json = {
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "sector_count":
            len(SECTORS),
        "processed_count":
            len(
                latest_results
            ),
        "failure_count":
            len(failures),
        "latest_base_date":
            max(base_dates)
            if base_dates
            else None,
        "results":
            latest_results,
        "failures":
            failures,
    }

    with open(
        OUTPUT_DIR
        / "sector_indices_latest.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            latest_json,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print()
    print("=== COMPLETE ===")
    print(
        "Processed:",
        len(latest_results),
        "/",
        len(SECTORS),
    )

    print(
        "Failures:",
        len(failures),
    )

    for row in latest_results:
        print(
            row["symbol"],
            row["sector"],
            row["base_date"],
            row["close"],
            "25MA:",
            row["ma25"],
            "RSI:",
            row["rsi14"],
        )


if __name__ == "__main__":
    main()
