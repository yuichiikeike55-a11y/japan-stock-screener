
"""
18セクター指数取得・指標生成。

TOPIX-17連動ETF 17銘柄 + 半導体ETF 2644.T。

- BASE_DATE時点のデータだけで計算
- 取得失敗時は再試行
- 18セクターの基準日一致を確認
- 品質警告を保存
- 不完全な結果は正式latestへ公開しない
- 失敗内容は別JSONに保存
"""

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


OUTPUT_DIR = Path("output")
HISTORY_DIR = OUTPUT_DIR / "sector_history"
LATEST_FILE = OUTPUT_DIR / "sector_indices_latest.json"
STATUS_FILE = OUTPUT_DIR / "sector_indices_status.json"

RETRY_COUNT = 3
RETRY_SECONDS = 10

SECTOR_NAMES = [
    "食品",
    "エネルギー資源",
    "建設・資材",
    "素材・化学",
    "医薬品",
    "自動車・輸送機",
    "鉄鋼・非鉄",
    "機械",
    "電機・精密",
    "情報通信・サービスその他",
    "電力・ガス",
    "運輸・物流",
    "商社・卸売",
    "小売",
    "銀行",
    "金融（除く銀行）",
    "不動産",
]

SECTORS = [
    {
        "sector": name,
        "symbol": f"{1617 + index}.T",
        "name": f"NEXT FUNDS {name}(TOPIX-17)ETF",
        "proxy_type": "ETF",
    }
    for index, name in enumerate(SECTOR_NAMES)
]

SECTORS.append(
    {
        "sector": "半導体",
        "symbol": "2644.T",
        "name": "Global X 半導体関連-日本株式 ETF",
        "proxy_type": "ETF",
    }
)


def safe_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    try:
        temporary.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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
    result = 100 - 100 / (1 + rs)

    result = result.mask(
        (avg_loss == 0) & (avg_gain > 0),
        100,
    )
    result = result.mask(
        (avg_loss == 0) & (avg_gain == 0),
        50,
    )

    return result


def download_history(symbol):
    last_error = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            df = yf.download(
                symbol,
                period="2y",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if df is None or df.empty:
                raise RuntimeError("empty response")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            required = [
                "Open", "High", "Low", "Close", "Volume"
            ]

            missing = [
                col for col in required
                if col not in df.columns
            ]

            if missing:
                raise RuntimeError(
                    f"missing columns: {missing}"
                )

            df = df[required].copy()

            index = pd.to_datetime(df.index)

            if index.tz is not None:
                index = index.tz_convert(
                    "Asia/Tokyo"
                ).tz_localize(None)

            df.index = index.normalize()
            df = df.sort_index()
            df = df.loc[~df.index.duplicated(keep="last")]

            if df.empty:
                raise RuntimeError("no valid dates")

            return df

        except Exception as exc:
            last_error = str(exc)
            print(
                f"{symbol}: attempt "
                f"{attempt}/{RETRY_COUNT}: "
                f"{last_error}",
                flush=True,
            )

            if attempt < RETRY_COUNT:
                time.sleep(RETRY_SECONDS)

    raise RuntimeError(
        f"{symbol}: download failed: {last_error}"
    )


def validate_ohlcv(df):
    x = df.copy()
    flags = []

    price_cols = ["Open", "High", "Low", "Close"]

    for col in price_cols:
        x[col] = pd.to_numeric(
            x[col], errors="coerce"
        )

    x["Volume"] = pd.to_numeric(
        x["Volume"], errors="coerce"
    )

    invalid_price = pd.Series(False, index=x.index)

    for col in price_cols:
        invalid_price |= (
            ~np.isfinite(x[col])
            | (x[col] <= 0)
        )

    if invalid_price.any():
        flags.append("invalid_price")

    invalid_ohlc = (
        (x["High"] < x["Low"])
        | (x["High"] < x["Open"])
        | (x["High"] < x["Close"])
        | (x["Low"] > x["Open"])
        | (x["Low"] > x["Close"])
    )

    if invalid_ohlc.any():
        flags.append("ohlc_inconsistency")

    bad_price = invalid_price | invalid_ohlc

    x.loc[bad_price, price_cols] = np.nan

    bad_volume = (
        ~np.isfinite(x["Volume"])
        | (x["Volume"] < 0)
    )

    if bad_volume.any():
        flags.append("invalid_volume")
        x.loc[bad_volume, "Volume"] = np.nan

    ratio = x["Close"] / x["Close"].shift(1)

    if ((ratio > 1.4) | (ratio < 0.6)).any():
        flags.append("extreme_daily_price_move_detected")

    median = x["Close"].rolling(
        21, center=True, min_periods=5
    ).median()

    for col in price_cols:
        distance = x[col] / median
        outlier = (
            (distance < 0.2)
            | (distance > 5.0)
        )

        if outlier.any():
            flags.append(
                f"{col.lower()}_extreme_outlier"
            )
            x.loc[outlier, col] = np.nan

    # 異常値を除いた後の有効日付だけを使用
    x = x.dropna(subset=["Close"])

    return x, list(dict.fromkeys(flags))


def calculate_metrics(df):
    x = df.copy()

    close = x["Close"]
    high = x["High"]
    low = x["Low"]
    volume = x["Volume"]

    x["ma5"] = close.rolling(5).mean()
    x["ma25"] = close.rolling(25).mean()
    x["ma75"] = close.rolling(75).mean()
    x["rsi14"] = calc_rsi(close, 14)

    x["high20"] = high.rolling(20).max()
    x["low20"] = low.rolling(20).min()
    x["high52"] = high.rolling(252).max()
    x["low52"] = low.rolling(252).min()

    x["avg_volume_5d"] = volume.rolling(5).mean()
    x["avg_volume_20d"] = volume.rolling(20).mean()

    return x


def gap_pct(value, base):
    a = safe_float(value)
    b = safe_float(base)

    if a is None or b is None or b == 0:
        return None

    return (a / b - 1) * 100


def build_latest_record(info, df, flags):
    if len(df) < 75:
        raise RuntimeError(
            f"not enough history: {len(df)} rows"
        )

    x = calculate_metrics(df)
    current = x.iloc[-1]
    previous = x.iloc[-2]

    close = safe_float(current["Close"])
    previous_close = safe_float(previous["Close"])

    if close is None or previous_close is None:
        raise RuntimeError("invalid latest close")

    ma5 = safe_float(current["ma5"])
    ma25 = safe_float(current["ma25"])
    ma75 = safe_float(current["ma75"])
    ma25_previous = safe_float(previous["ma25"])

    ma25_slope = (
        ma25 - ma25_previous
        if ma25 is not None
        and ma25_previous is not None
        else None
    )

    direction = None

    if ma25_slope is not None:
        direction = (
            "up" if ma25_slope > 0
            else "down" if ma25_slope < 0
            else "flat"
        )

    high52 = safe_float(current["high52"])
    low52 = safe_float(current["low52"])

    if high52 is not None and high52 < close:
        flags.append("invalid_high52_below_close")
        high52 = None

    if low52 is not None and low52 > close:
        flags.append("invalid_low52_above_close")
        low52 = None

    if low52 is not None and low52 < close * 0.1:
        flags.append("invalid_low52_extreme_outlier")
        low52 = None

    volume = safe_float(current["Volume"])
    avg20 = safe_float(current["avg_volume_20d"])

    return {
        "sector": info["sector"],
        "symbol": info["symbol"],
        "name": info["name"],
        "proxy_type": info["proxy_type"],
        "source": "yfinance",
        "base_date": df.index[-1].strftime("%Y-%m-%d"),
        "data_quality_status": (
            "warning" if flags else "ok"
        ),
        "data_quality_flags": list(dict.fromkeys(flags)),
        "open": safe_float(current["Open"]),
        "high": safe_float(current["High"]),
        "low": safe_float(current["Low"]),
        "close": close,
        "volume": volume,
        "ma5": ma5,
        "ma25": ma25,
        "ma75": ma75,
        "ma25_previous": ma25_previous,
        "ma25_slope": safe_float(ma25_slope),
        "ma25_direction": direction,
        "ma5_gap_pct": gap_pct(close, ma5),
        "ma25_gap_pct": gap_pct(close, ma25),
        "ma75_gap_pct": gap_pct(close, ma75),
        "rsi14": safe_float(current["rsi14"]),
        "high20": safe_float(current["high20"]),
        "low20": safe_float(current["low20"]),
        "high52": high52,
        "low52": low52,
        "high20_gap_pct": gap_pct(
            close, current["high20"]
        ),
        "high52_gap_pct": gap_pct(close, high52),
        "return_1d_pct": gap_pct(
            close, previous_close
        ),
        "return_5d_pct": (
            gap_pct(close, x.iloc[-6]["Close"])
            if len(x) >= 6 else None
        ),
        "return_20d_pct": (
            gap_pct(close, x.iloc[-21]["Close"])
            if len(x) >= 21 else None
        ),
        "avg_volume_5d": safe_float(
            current["avg_volume_5d"]
        ),
        "avg_volume_20d": avg20,
        "volume_ratio_20d": (
            volume / avg20
            if volume is not None
            and avg20 is not None
            and avg20 > 0
            else None
        ),
    }


def build_history_records(df):
    rows = []

    for index, row in df.tail(300).iterrows():
        rows.append({
            "date": index.strftime("%Y-%m-%d"),
            "open": safe_float(row["Open"]),
            "high": safe_float(row["High"]),
            "low": safe_float(row["Low"]),
            "close": safe_float(row["Close"]),
            "volume": safe_float(row["Volume"]),
        })

    return rows


def main():
    raw_date = os.getenv("BASE_DATE", "").strip()

    requested_date = (
        pd.Timestamp(raw_date).normalize()
        if raw_date else None
    )

    latest_results = []
    failures = []
    history_payloads = []

    for info in SECTORS:
        symbol = info["symbol"]

        try:
            print(
                "Downloading:",
                symbol,
                info["sector"],
                flush=True,
            )

            df = download_history(symbol)

            # 要求日より後のデータは計算に混ぜない
            if requested_date is not None:
                df = df.loc[
                    df.index <= requested_date
                ].copy()

                if df.empty:
                    raise RuntimeError(
                        "no data on or before BASE_DATE"
                    )

                if df.index[-1] != requested_date:
                    raise RuntimeError(
                        "BASE_DATE bar missing; "
                        f"latest={df.index[-1].date()}"
                    )

            df, flags = validate_ohlcv(df)

            if df.empty:
                raise RuntimeError(
                    "no valid OHLCV data"
                )

            if (
                requested_date is not None
                and df.index[-1] != requested_date
            ):
                raise RuntimeError(
                    "BASE_DATE bar invalid after quality checks"
                )

            record = build_latest_record(
                info, df, flags
            )

            latest_results.append(record)

            history_payloads.append((
                HISTORY_DIR / (
                    symbol.replace(".", "_") + ".json"
                ),
                {
                    "sector": info["sector"],
                    "symbol": symbol,
                    "name": info["name"],
                    "proxy_type": info["proxy_type"],
                    "source": "yfinance",
                    "base_date": record["base_date"],
                    "generated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "history": build_history_records(df),
                },
            ))

        except Exception as exc:
            print(
                "FAILED:", symbol, str(exc),
                flush=True,
            )

            failures.append({
                "sector": info["sector"],
                "symbol": symbol,
                "error": str(exc),
            })

    dates = {
        item["base_date"]
        for item in latest_results
    }

    expected = (
        requested_date.strftime("%Y-%m-%d")
        if requested_date is not None else None
    )

    complete = (
        len(latest_results) == 18
        and len(failures) == 0
        and len(dates) == 1
        and (
            expected is None
            or dates == {expected}
        )
    )

    status = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "requested_base_date": expected,
        "evaluation_status": (
            "ok" if complete else "unavailable"
        ),
        "sector_count": 18,
        "processed_count": len(latest_results),
        "failure_count": len(failures),
        "observed_base_dates": sorted(dates),
        "failures": failures,
    }

    atomic_json(STATUS_FILE, status)

    if not complete:
        # 以前の正常データを今回の結果と誤認させない。
        # screener側でも必ずBASE_DATEを照合する。
        raise RuntimeError(
            "18-sector data incomplete or date mismatch. "
            f"processed={len(latest_results)}/18, "
            f"failures={len(failures)}, "
            f"dates={sorted(dates)}. "
            "Official latest file was not overwritten."
        )

    payload = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "sector_count": 18,
        "processed_count": 18,
        "failure_count": 0,
        "latest_base_date": next(iter(dates)),
        "results": latest_results,
        "failures": [],
    }

    # 完全な18セクターが揃ってから公開する
    for path, history in history_payloads:
        atomic_json(path, history)

    atomic_json(LATEST_FILE, payload)

    print("=== COMPLETE ===")
    print("Base date:", payload["latest_base_date"])
    print("Processed: 18/18")
    print("Failures: 0")


if __name__ == "__main__":
    main()
