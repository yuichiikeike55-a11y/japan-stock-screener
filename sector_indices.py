
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



def validate_ohlcv(df):
    x = df.copy()
    flags = []

    for col in [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]:
        x[col] = pd.to_numeric(
            x[col],
            errors="coerce",
        )

    invalid_price = (
        (x["Open"] <= 0)
        | (x["High"] <= 0)
        | (x["Low"] <= 0)
        | (x["Close"] <= 0)
        | (x["High"] < x["Low"])
        | (x["High"] < x["Open"])
        | (x["High"] < x["Close"])
        | (x["Low"] > x["Open"])
        | (x["Low"] > x["Close"])
    )

    if invalid_price.any():
        flags.append("invalid_ohlc")
        x.loc[invalid_price, "Close"] = np.nan

    invalid_volume = (
        (x["Volume"] < 0)
        | (~np.isfinite(x["Volume"]))
    )

    if invalid_volume.any():
        flags.append("invalid_volume")
        x.loc[invalid_volume, "Volume"] = np.nan

    x = x.dropna(subset=["Close"])

    return x, flags


def download_history(symbol):
    requested = os.environ.get("BASE_DATE", "").strip()

    if requested:
        target = pd.Timestamp(requested).normalize()
    else:
        target = None

    if target is not None:
        start_date = target - pd.Timedelta(days=850)
        end_date = target + pd.Timedelta(days=2)

        df = yf.download(
            symbol,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    else:
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

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    missing = [
        col for col in required
        if col not in df.columns
    ]

    if missing:
        raise ValueError(
            f"{symbol}: missing columns {missing}"
        )

    df = df[required].copy()
    df.index = pd.to_datetime(df.index)

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    df.index = df.index.normalize()
    df = df.sort_index()

    if target is not None:
        df = df.loc[df.index <= target].copy()

        if target not in df.index:
            latest = (
                str(df.index.max().date())
                if not df.empty
                else "none"
            )
            raise ValueError(
                f"{symbol}: BASE_DATE bar missing; "
                f"latest={latest}"
            )

        raw_target = df.loc[target].copy()

        print(
            "[SECTOR RAW TARGET]",
            symbol,
            target.date(),
            raw_target.to_dict(),
            flush=True,
        )


    df = df.dropna(subset=["Close"])

    if target is not None and target not in df.index:
        raise ValueError(
            f"{symbol}: BASE_DATE Close missing; "
            f"raw_ohlcv={raw_target.to_dict()}"
        )

    print(
        "[SECTOR DOWNLOAD]",
        symbol,
        "rows=", len(df),
        "latest=",
        str(df.index.max().date()) if not df.empty else "none",
        flush=True,
    )

    return df

    print(
        "[SECTOR DOWNLOAD]",
        symbol,
        "rows=", len(df),
        "latest=",
        str(df.index.max().date()) if not df.empty else "none",
        "flags=", quality_flags,
        flush=True,
    )

    return df


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


            raw_target = (
                df.loc[requested_date].to_dict()
                if requested_date is not None
                and requested_date in df.index
                else None
            )

            df, flags = validate_ohlcv(df)

            if (
                requested_date is not None
                and requested_date not in df.index
            ):
                raise RuntimeError(
                    "BASE_DATE bar invalid after quality checks; "
                    f"raw_ohlcv={raw_target}; "
                    f"quality_flags={flags}"
                )


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
        "requested_date": expected,
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

    partial_payload = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "publication_status": "provisional",
        "requested_base_date": expected,
        "sector_count": 18,
        "processed_count": len(latest_results),
        "failure_count": len(failures),
        "observed_base_dates": sorted(dates),
        "results": latest_results,
        "failures": failures,
    }

    atomic_json(
        OUTPUT_DIR / "sector_indices_provisional_latest.json",
        partial_payload,
    )


    
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
    import time

    max_attempts = 3
    retry_seconds = 300

    for attempt in range(1, max_attempts + 1):
        print(
            f"\n=== SECTOR ATTEMPT "
            f"{attempt}/{max_attempts} ===",
            flush=True,
        )

        try:
            main()
            print(
                "SECTOR DATA READY: "
                "18 sectors validated",
                flush=True,
            )
            break

        except RuntimeError as exc:
            print(
                f"SECTOR ATTEMPT FAILED: {exc}",
                flush=True,
            )

            if attempt == max_attempts:
                raise

            print(
                f"Retrying in {retry_seconds} seconds...",
                flush=True,
            )
            time.sleep(retry_seconds)
