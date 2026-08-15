import os
import json
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup


# ============================================================
# 設定
# ============================================================

PRICE_MIN = 1000
PRICE_MAX = 4000

HIGH52_GAP_MIN = -8.0
HIGH52_GAP_MAX = -3.0

AVG_TURNOVER_5D_MIN = 1_000_000_000

VOLUME_RATIO_MIN = 1.2
VOLUME_RATIO_MAX = 2.0

MA5_GAP_MIN = 0.0

MA25_GAP_MIN = -2.0
MA25_GAP_MAX = 3.0

LOOKBACK_DAYS = 600
BATCH_SIZE = 50
RETRIES = 3

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

JPX_PAGES = [
    "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html",
    "https://www.jpx.co.jp/listing/co-search/01.html",
]


# ============================================================
# 共通関数
# ============================================================

def clean_code(value):
    s = str(value).strip()

    if s.endswith(".0"):
        s = s[:-2]

    digits = "".join(c for c in s if c.isdigit())

    if len(digits) == 4:
        return digits

    return None


def find_column(columns, keywords):
    for col in columns:
        text = str(col).replace(" ", "").replace("\n", "")
        for keyword in keywords:
            if keyword in text:
                return col
    return None


# ============================================================
# JPX 上場銘柄一覧
# ============================================================

def find_jpx_excel():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for page_url in JPX_PAGES:
        try:
            r = requests.get(page_url, headers=headers, timeout=30)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]

                if ".xlsx" not in href.lower() and ".xls" not in href.lower():
                    continue

                if href.startswith("http"):
                    url = href
                else:
                    url = requests.compat.urljoin(page_url, href)

                print("JPX Excel candidate:", url)
                return url

        except Exception as e:
            print("JPX page error:", page_url, e)

    raise RuntimeError(
        "JPXの上場銘柄一覧Excelを自動検出できませんでした。"
        "JPXサイト構成が変更された可能性があります。"
    )


def load_prime_universe():
    excel_url = find_jpx_excel()

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(excel_url, headers=headers, timeout=60)
    r.raise_for_status()

    df = pd.read_excel(BytesIO(r.content))

    print("JPX columns:")
    print(list(df.columns))

    code_col = find_column(
        df.columns,
        ["コード", "Code"]
    )

    name_col = find_column(
        df.columns,
        ["銘柄名", "会社名", "名称", "Name"]
    )

    market_col = find_column(
        df.columns,
        ["市場・商品区分", "市場区分", "市場", "Market"]
    )

    if code_col is None:
        raise RuntimeError("JPXファイルの銘柄コード列を特定できません。")

    if market_col is None:
        raise RuntimeError("JPXファイルの市場区分列を特定できません。")

    if name_col is None:
        df["_name"] = ""
        name_col = "_name"

    df["_code"] = df[code_col].apply(clean_code)

    market_text = df[market_col].astype(str)

    prime = df[
        market_text.str.contains("プライム", na=False)
        & df["_code"].notna()
    ].copy()

    prime = prime[
        ["_code", name_col, market_col]
    ].copy()

    prime.columns = [
        "code",
        "name",
        "market"
    ]

    prime["ticker"] = prime["code"] + ".T"

    prime = (
        prime
        .drop_duplicates("code")
        .sort_values("code")
        .reset_index(drop=True)
    )

    print("Prime universe:", len(prime))

    return prime


# ============================================================
# yfinance
# ============================================================

def download_one(ticker, start, end):
    for attempt in range(RETRIES):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
            )

            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                required = {"High", "Close", "Volume"}

                if required.issubset(df.columns):
                    return df[
                        ["High", "Close", "Volume"]
                    ].copy()

        except Exception as e:
            print(
                f"{ticker} attempt {attempt + 1} error:",
                e
            )

        time.sleep(2)

    return None


def download_prices(universe, base_date=None):
    if base_date is not None:
        end_date = base_date + pd.Timedelta(days=1)
    else:
        end_date = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None) + pd.Timedelta(days=1)

    start_date = end_date - pd.Timedelta(days=LOOKBACK_DAYS)

    all_data = {}
    failures = []

    tickers = universe["ticker"].tolist()

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]

        print(
            f"Downloading {i + 1}-"
            f"{min(i + BATCH_SIZE, len(tickers))}"
            f" / {len(tickers)}"
        )

        try:
            data = yf.download(
                batch,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                auto_adjust=False,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
            )

        except Exception as e:
            print("Batch error:", e)
            data = None

        for ticker in batch:
            ticker_df = None

            try:
                if data is not None and not data.empty:
                    if isinstance(data.columns, pd.MultiIndex):
                        level0 = data.columns.get_level_values(0)

                        if ticker in level0:
                            ticker_df = data[ticker].copy()

                    elif len(batch) == 1:
                        ticker_df = data.copy()

                if ticker_df is not None:
                    required = {"High", "Close", "Volume"}

                    if not required.issubset(ticker_df.columns):
                        ticker_df = None

                if ticker_df is not None:
                    ticker_df = ticker_df[
                        ["High", "Close", "Volume"]
                    ].dropna(how="all")

                    if ticker_df.empty:
                        ticker_df = None

            except Exception:
                ticker_df = None

            if ticker_df is None:
                print("Retry individually:", ticker)

                ticker_df = download_one(
                    ticker,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                )

            if ticker_df is not None and not ticker_df.empty:
                ticker_df.index = pd.to_datetime(
                    ticker_df.index
                ).tz_localize(None)

                if (
                    base_date is not None
                    and ticker_df.index[-1].normalize()
                    < base_date
                ):
                    print(
                        "Retry stale data:",
                        ticker,
                        "last_date:",
                        ticker_df.index[-1].date()
                    )

                    retry_df = download_one(
                        ticker,
                        start_date.strftime("%Y-%m-%d"),
                        end_date.strftime("%Y-%m-%d"),
                    )

                    if retry_df is not None and not retry_df.empty:
                        retry_df.index = pd.to_datetime(
                            retry_df.index
                        ).tz_localize(None)

                        if retry_df.index[-1] > ticker_df.index[-1]:
                            ticker_df = retry_df

            if ticker_df is None or ticker_df.empty:
                failures.append({
                    "ticker": ticker,
                    "reason": "download_failed"
                })
            else:
                all_data[ticker] = ticker_df

        time.sleep(1)

    return all_data, failures


# ============================================================
# 基準日
# ============================================================

def choose_base_date(price_data, requested=None):
    if requested is not None:
        return pd.Timestamp(requested).normalize()

    counts = {}

    for df in price_data.values():
        for d in df.index:
            d = pd.Timestamp(d).normalize()
            counts[d] = counts.get(d, 0) + 1

    if not counts:
        raise RuntimeError("株価データを取得できませんでした。")

    total = len(price_data)

    candidates = sorted(
        counts.keys(),
        reverse=True
    )

    for d in candidates:
        coverage = counts[d] / total

        if coverage >= 0.90:
            return d

    raise RuntimeError(
        "90%以上の銘柄で共通する最新取引日を"
        "特定できませんでした。"
    )


# ============================================================
# 指標計算
# ============================================================

def calculate_metrics(
    universe,
    price_data,
    base_date
):
    metrics = []
    failures = []

    lookup = universe.set_index("ticker")

    for ticker, df in price_data.items():
        code = ticker.replace(".T", "")

        try:
            name = lookup.loc[ticker, "name"]
            market = lookup.loc[ticker, "market"]
        except Exception:
            name = ""
            market = "Prime"

        x = df.copy()

        x = x[
            x.index.normalize()
            <= base_date
        ].copy()

        x = x.sort_index()

        if x.empty:
            failures.append({
                "code": code,
                "name": name,
                "reason": "no_data_before_base_date"
            })
            continue

        if x.index[-1].normalize() != base_date:
            failures.append({
                "code": code,
                "name": name,
                "reason": "base_date_missing",
                "last_date": x.index[-1].strftime("%Y-%m-%d")
            })
            continue

        if len(x) < 252:
            failures.append({
                "code": code,
                "name": name,
                "reason": f"insufficient_history_{len(x)}"
            })
            continue

        close = pd.to_numeric(
            x["Close"],
            errors="coerce"
        )

        high = pd.to_numeric(
            x["High"],
            errors="coerce"
        )

        volume = pd.to_numeric(
            x["Volume"],
            errors="coerce"
        )

        if (
            close.tail(25).isna().any()
            or high.tail(252).isna().any()
            or volume.tail(21).isna().any()
        ):
            failures.append({
                "code": code,
                "name": name,
                "reason": "nan_in_required_window"
            })
            continue

        current_close = float(close.iloc[-1])
        current_volume = float(volume.iloc[-1])

        previous_volume = float(volume.iloc[-2])

        if previous_volume <= 0:
            failures.append({
                "code": code,
                "name": name,
                "reason": "invalid_previous_volume"
            })
            continue

        volume_ratio_prev = (
            current_volume
            / previous_volume
        )

        delta = close.diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.iloc[1:15].mean()
        avg_loss = loss.iloc[1:15].mean()

        for i in range(15, len(close)):
            avg_gain = (
                avg_gain * 13
                + gain.iloc[i]
            ) / 14

            avg_loss = (
                avg_loss * 13
                + loss.iloc[i]
            ) / 14

        if avg_loss == 0:
            rsi14 = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi14 = 100.0 - (
                100.0 / (1.0 + rs)
            )
        
        ma5 = float(
            close.tail(5).mean()
        )

        ma25 = float(
            close.tail(25).mean()
        )

        high52 = float(
            high.tail(252).max()
        )

        volume_20d_ago = float(
            volume.iloc[-21]
        )

        if volume_20d_ago <= 0:
            failures.append({
                "code": code,
                "name": name,
                "reason": "invalid_volume_20d_ago"
            })
            continue

        turnover_5d = (
            close.tail(5)
            * volume.tail(5)
        )

        avg_turnover_5d = float(
            turnover_5d.mean()
        )

        ma5_gap = (
            current_close / ma5 - 1
        ) * 100

        ma25_gap = (
            current_close / ma25 - 1
        ) * 100

        high52_gap = (
            current_close / high52 - 1
        ) * 100

        volume_ratio = (
            current_volume
            / volume_20d_ago
        )

        metrics.append({
            "code": code,
            "name": str(name),
            "market": str(market),
            "base_date": base_date.strftime("%Y-%m-%d"),
            "close": current_close,
            "ma5": ma5,
            "ma25": ma25,
            "high52": high52,
            "ma5_gap_pct": ma5_gap,
            "ma25_gap_pct": ma25_gap,
            "high52_gap_pct": high52_gap,
            "avg_turnover_5d": avg_turnover_5d,
            "volume": current_volume,
            "previous_volume": previous_volume,
"volume_ratio_prev": volume_ratio_prev,
"rsi14": rsi14,
            "volume_20d_ago": volume_20d_ago,
            "volume_ratio_20d": volume_ratio,
        })

    return pd.DataFrame(metrics), failures


# ============================================================
# スクリーニング
# ============================================================

def apply_screen(metrics):
  def apply_reacceleration_screen(metrics):
    if metrics.empty:
        return metrics.copy()

    mask = (
        metrics["close"].between(
            700,
            4000,
            inclusive="both"
        )
        &
        metrics["high52_gap_pct"].between(
            -10,
            -3,
            inclusive="both"
        )
        &
        (
            metrics["avg_turnover_5d"]
            >= 1_500_000_000
        )
        &
        metrics["volume_ratio_prev"].between(
            1.2,
            2.5,
            inclusive="both"
        )
        &
        metrics["ma25_gap_pct"].between(
            -3,
            5,
            inclusive="both"
        )
        &
        metrics["rsi14"].between(
            45,
            60,
            inclusive="both"
        )
        &
        (
            metrics["volume"]
            >= 1_500_000
        )
    )

    result = metrics[mask].copy()

    result = result.sort_values(
        "avg_turnover_5d",
        ascending=False
    )

    return result
    if metrics.empty:
        return metrics.copy()

    mask = (
        metrics["close"].between(
            PRICE_MIN,
            PRICE_MAX,
            inclusive="both"
        )
        &
        metrics["high52_gap_pct"].between(
            HIGH52_GAP_MIN,
            HIGH52_GAP_MAX,
            inclusive="both"
        )
        &
        (
            metrics["avg_turnover_5d"]
            >= AVG_TURNOVER_5D_MIN
        )
        &
        metrics["volume_ratio_20d"].between(
            VOLUME_RATIO_MIN,
            VOLUME_RATIO_MAX,
            inclusive="both"
        )
        &
        (
            metrics["ma5_gap_pct"]
            >= MA5_GAP_MIN
        )
        &
        metrics["ma25_gap_pct"].between(
            MA25_GAP_MIN,
            MA25_GAP_MAX,
            inclusive="both"
        )
    )

    result = metrics[mask].copy()

    result = result.sort_values(
        "avg_turnover_5d",
        ascending=False
    )

    return result.head(10)


# ============================================================
# JSON用
# ============================================================

def safe_records(df):
    if df.empty:
        return []

    x = df.copy()

    x = x.replace(
        [np.inf, -np.inf],
        np.nan
    )

    x = x.where(
        pd.notnull(x),
        None
    )

    return x.to_dict(
        orient="records"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=== Japan Stock 25MA Screener ===")

    requested_date = os.getenv(
        "BASE_DATE",
        ""
    ).strip()

    if requested_date:
        requested_date = pd.Timestamp(
            requested_date
        ).normalize()
        print(
            "Requested base date:",
            requested_date.date()
        )
    else:
        requested_date = None
        print(
            "BASE_DATE not specified."
        )

    # 1. Prime universe
    universe = load_prime_universe()

    universe_count = len(universe)

    # 2. Prices
    price_data, download_failures = (
        download_prices(
            universe,
            requested_date
        )
    )

        # 3. Base date
    base_date = choose_base_date(
        price_data,
        requested_date
    )

    print(
        "Base date:",
        base_date.date()
    )

    # Retry only tickers that do not reach base_date
    retry_end_date = base_date + pd.Timedelta(days=1)
    retry_start_date = (
        retry_end_date - pd.Timedelta(days=LOOKBACK_DAYS)
    )

    stale_tickers = []

    for ticker, ticker_df in price_data.items():
        if ticker_df is None or ticker_df.empty:
            continue

        ticker_df.index = pd.to_datetime(
            ticker_df.index
        ).tz_localize(None)

        last_date = ticker_df.index[-1]

        if last_date < base_date:
            stale_tickers.append(ticker)

    print(
        "Stale tickers to retry:",
        len(stale_tickers)
    )

    for ticker in stale_tickers:
        try:
            print(
                "Retrying stale ticker:",
                ticker,
                retry_start_date.date(),
                retry_end_date.date()
            )

            retry_df = download_one(
                ticker,
                retry_start_date.strftime("%Y-%m-%d"),
                retry_end_date.strftime("%Y-%m-%d"),
            )

            if retry_df is None:
                print(
                    "Retry result is None:",
                    ticker
                )
                continue

            if retry_df.empty:
                print(
                    "Retry result is empty:",
                    ticker
                )
                continue

            retry_df.index = pd.to_datetime(
                retry_df.index
            ).tz_localize(None)

            print(
                "Retry last date:",
                ticker,
                retry_df.index[-1].date()
            )

            print(
                "Retry columns:",
                ticker,
                list(retry_df.columns)
            )

            required = {
                "High",
                "Close",
                "Volume"
            }

            if not required.issubset(
                retry_df.columns
            ):
                print(
                    "Retry missing columns:",
                    ticker
                )
                continue

            retry_df = retry_df[
                ["High", "Close", "Volume"]
            ].dropna(how="all")

            if retry_df.empty:
                print(
                    "Retry empty after dropna:",
                    ticker
                )
                continue

            if retry_df.index[-1] >= base_date:
                price_data[ticker] = retry_df

                print(
                    "Stale retry updated:",
                    ticker,
                    retry_df.index[-1].date()
                )
            else:
                print(
                    "Stale retry still old:",
                    ticker,
                    retry_df.index[-1].date()
                )

        except Exception as e:
            print(
                "Stale retry failed:",
                ticker,
                repr(e)
            )

    # 4. Metrics
    metrics, metric_failures = (
        calculate_metrics(
            universe,
            price_data,
            base_date
        )
    )

    # 5. Screen
    result = apply_screen(metrics)

    # 6. Failure table
    failure_rows = []

    ticker_to_name = dict(
        zip(
            universe["ticker"],
            universe["name"]
        )
    )

    for item in download_failures:
        ticker = item["ticker"]

        failure_rows.append({
            "code": ticker.replace(".T", ""),
            "name": ticker_to_name.get(
                ticker,
                ""
            ),
            "reason": item["reason"]
        })

    failure_rows.extend(
        metric_failures
    )

    failures_df = pd.DataFrame(
        failure_rows
    )

    processed_count = len(metrics)

    failure_count = (
        universe_count
        - processed_count
    )

    coverage_pct = (
        processed_count
        / universe_count
        * 100
        if universe_count
        else 0
    )

    # 7. Save CSV
    metrics.to_csv(
        OUTPUT_DIR / "all_metrics.csv",
        index=False,
        encoding="utf-8-sig"
    )

    failures_df.to_csv(
        OUTPUT_DIR / "failures.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # 8. latest.json
    latest = {
        "strategy": "25MA_pullback",
        "base_date": base_date.strftime(
            "%Y-%m-%d"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "universe_count": universe_count,
        "processed_count": processed_count,
        "coverage_pct": round(
            coverage_pct,
            2
        ),
        "eligible_count": len(result),
        "results": safe_records(
            result
        )
    }

    with open(
        OUTPUT_DIR / "latest.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            latest,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    # 9. health.json
    health = {
        "status": (
            "ok"
            if processed_count
            == universe_count
            else "partial"
        ),
        "base_date": base_date.strftime(
            "%Y-%m-%d"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "universe_count": universe_count,
        "processed_count": processed_count,
        "failure_count": failure_count,
        "coverage_pct": round(
            coverage_pct,
            2
        )
    }

    with open(
        OUTPUT_DIR / "health.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            health,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    # 10. Console
    print()
    print("=== COMPLETE ===")
    print(
        "Universe:",
        universe_count
    )
    print(
        "Processed:",
        processed_count
    )
    print(
        "Coverage:",
        f"{coverage_pct:.2f}%"
    )
    print(
        "Eligible:",
        len(result)
    )

    if not result.empty:
        print()
        print(
            result[
                [
                    "code",
                    "name",
                    "close",
                    "high52_gap_pct",
                    "ma5_gap_pct",
                    "ma25_gap_pct",
                    "avg_turnover_5d",
                    "volume_ratio_20d",
                ]
            ].to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()
