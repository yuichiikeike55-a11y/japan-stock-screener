import os
import json
import time
from io import BytesIO, StringIO
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

JPX_DELISTED_URL = (
    "https://www.jpx.co.jp/listing/stocks/delisted/index.html"
)


# ============================================================
# 共通関数
# ============================================================

def make_json_safe(obj):
    if isinstance(obj, dict):
        return {
            key: make_json_safe(value)
            for key, value in obj.items()
        }

    if isinstance(obj, list):
        return [
            make_json_safe(value)
            for value in obj
        ]

    if isinstance(obj, tuple):
        return [
            make_json_safe(value)
            for value in obj
        ]

    if isinstance(obj, (float, np.floating)):
        if not np.isfinite(obj):
            return None
        return float(obj)

    if isinstance(obj, np.integer):
        return int(obj)

    if isinstance(obj, np.bool_):
        return bool(obj)

    return obj


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
def load_delisted_codes(base_date):
    headers = {"User-Agent": "Mozilla/5.0"}

    r = requests.get(
        JPX_DELISTED_URL,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()

    tables = pd.read_html(StringIO(r.text))

    base_date = pd.Timestamp(base_date).normalize()
    delisted_codes = set()
    found_table = False

    for df in tables:
        date_col = find_column(
            df.columns,
            ["上場廃止日"],
        )
        code_col = find_column(
            df.columns,
            ["コード", "Code"],
        )

        if date_col is None or code_col is None:
            continue

        found_table = True

        for _, row in df.iterrows():
            delisted_date = pd.to_datetime(
                row[date_col],
                errors="coerce",
            )
            code = clean_code(row[code_col])

            if pd.isna(delisted_date) or code is None:
                continue

            delisted_date = pd.Timestamp(
                delisted_date
            ).normalize()

            if delisted_date <= base_date:
                delisted_codes.add(code)

    if not found_table:
        raise RuntimeError(
            "JPX delisted-stock table was not found"
        )

    print(
        "JPX delisted codes on/before base date:",
        len(delisted_codes),
    )

    return delisted_codes


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

                required = {
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                }

                if required.issubset(df.columns):
                    return df[
                        [
                            "Open",
                            "High",
                            "Low",
                            "Close",
                            "Volume",
                        ]
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
                    required = {
                        "Open",
                        "High",
                        "Low",
                        "Close",
                        "Volume",
                    }

                    if not required.issubset(ticker_df.columns):
                        ticker_df = None

                if ticker_df is not None:
                    ticker_df = ticker_df[
                        [
                            "Open",
                            "High",
                            "Low",
                            "Close",
                            "Volume",
                        ]
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
def calculate_rci(series, period):
    values = pd.to_numeric(
        series.tail(period),
        errors="coerce"
    )

    if len(values) < period or values.isna().any():
        return np.nan

    n = len(values)

    date_rank = np.arange(
        n,
        0,
        -1,
        dtype=float
    )

    price_rank = values.rank(
        ascending=False,
        method="average"
    ).to_numpy(dtype=float)

    d = date_rank - price_rank

    denominator = (
        n
        * (n ** 2 - 1)
    )

    if denominator == 0:
        return np.nan

    rci = (
        1.0
        - (
            6.0
            * np.sum(d ** 2)
            / denominator
        )
    ) * 100.0

    return float(rci)

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

        # ここは各銘柄を処理している for ループの中

        history_days = len(x)

        if history_days < 75:
            failures.append({
                "code": code,
                "name": name,
                "reason": f"insufficient_history_{history_days}"
            })
            continue

        high52_available = history_days >= 252

        open_price = pd.to_numeric(
            x["Open"],
            errors="coerce"
        )

        high = pd.to_numeric(
            x["High"],
            errors="coerce"
        )

        low = pd.to_numeric(
            x["Low"],
            errors="coerce"
        )

        close = pd.to_numeric(
            x["Close"],
            errors="coerce"
        )


        volume = pd.to_numeric(
            x["Volume"],
            errors="coerce"
        )

        required_nan = (
            open_price.tail(2).isna().any()
            or high.tail(20).isna().any()
            or low.tail(20).isna().any()
            or close.tail(75).isna().any()
            or volume.tail(21).isna().any()
        )

        if high52_available:
            required_nan = (
                required_nan
                or high.tail(252).isna().any()
            )

        if required_nan:
            failures.append({
                "code": code,
                "name": name,
                "reason": "nan_in_required_window"
            })
            continue

        current_open = float(
            open_price.iloc[-1]
        )

        current_high = float(
            high.iloc[-1]
        )

        current_low = float(
            low.iloc[-1]
        )

        current_close = float(
            close.iloc[-1]
        )

        current_volume = float(
            volume.iloc[-1]
        )

        previous_open = float(
            open_price.iloc[-2]
        )

        previous_high = float(
            high.iloc[-2]
        )

        previous_low = float(
            low.iloc[-2]
        )

        previous_close = float(
            close.iloc[-2]
        )

        previous_volume = float(
            volume.iloc[-2]
        )

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

        gain_sum = gain.tail(14).sum()
        loss_sum = loss.tail(14).sum()

        total_move = (
            gain_sum
            + loss_sum
        )

        if total_move == 0:
            rsi14 = 50.0
        else:
            rsi14 = (
                gain_sum
                / total_move
                * 100.0
            )

        ma5 = float(
            close.tail(5).mean()
        )

        ma25 = float(
            close.tail(25).mean()
        )

        ma75 = float(
            close.tail(75).mean()
        )

        ma25_previous = float(
            close.iloc[:-1].tail(25).mean()
        )

        ma25_slope = (
            ma25
            - ma25_previous
        )

        if ma25_slope > 0:
            ma25_direction = "up"
        elif ma25_slope < 0:
            ma25_direction = "down"
        else:
            ma25_direction = "flat"

        rci9 = calculate_rci(
            close,
            9
        )

        rci27 = calculate_rci(
            close,
            27
        )

        if high52_available:
            high52 = float(
                high.tail(252).max()
            )
        else:
            high52 = None

        high20 = float(
            high.tail(20).max()
        )

        high20 = float(
            high.tail(20).max()
        )

        low20 = float(
            low.tail(20).min()
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
            current_close
            / ma5
            - 1
        ) * 100

        ma25_gap = (
            current_close
            / ma25
            - 1
        ) * 100

        if high52_available:
            high52_gap = (
                current_close
                / high52
                - 1
            ) * 100
        else:
            high52_gap = None

        high20_gap = (
            current_close
            / high20
            - 1
        ) * 100

        volume_ratio = (
            current_volume
            / volume_20d_ago
        )

        touched_ma25 = bool(
            current_low <= ma25
            <= current_high
        )

        recovered_ma25 = bool(
            current_low < ma25
            and current_close >= ma25
        )

        metrics.append({
            "code": code,
            "name": str(name),
            "market": str(market),
            "base_date": base_date.strftime("%Y-%m-%d"),
            "history_days": history_days,
            "high52_available": high52_available,
            "open": current_open,
            "high": current_high,
            "low": current_low,
            "close": current_close,

            "previous_open": previous_open,
            "previous_high": previous_high,
            "previous_low": previous_low,
            "previous_close": previous_close,

            "ma5": ma5,
            "ma25": ma25,
            "ma75": ma75,

            "ma25_previous": ma25_previous,
            "ma25_slope": ma25_slope,
            "ma25_direction": ma25_direction,

            "rci9": rci9,
            "rci27": rci27,
            "rsi14": rsi14,

            "high52": high52,
            "high20": high20,
            "low20": low20,

            "ma5_gap_pct": ma5_gap,
            "ma25_gap_pct": ma25_gap,
            "high52_gap_pct": high52_gap,
            "high20_gap_pct": high20_gap,

            "touched_ma25": touched_ma25,
            "recovered_ma25": recovered_ma25,

            "avg_turnover_5d": avg_turnover_5d,

            "volume": current_volume,
            "previous_volume": previous_volume,
            "volume_ratio_prev": volume_ratio_prev,

            "volume_20d_ago": volume_20d_ago,
            "volume_ratio_20d": volume_ratio,
        })

    return pd.DataFrame(metrics), failures


# ============================================================
# スクリーニング
# ============================================================

def apply_screen(metrics):
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
def apply_initial_breakout_screen(metrics):
    if metrics.empty:
        return metrics.copy()

    mask = (
        metrics["close"].between(
            1000,
            5000,
            inclusive="both"
        )
        &
        metrics["high52_gap_pct"].between(
            -6,
            1,
            inclusive="both"
        )
        &
        (
            metrics["avg_turnover_5d"]
            >= 1_500_000_000
        )
        &
        metrics["volume_ratio_prev"].between(
            1.3,
            2.5,
            inclusive="both"
        )
        &
        metrics["ma25_gap_pct"].between(
            0,
            8,
            inclusive="both"
        )
        &
        metrics["rsi14"].between(
            50,
            65,
            inclusive="both"
        )
    )

    result = metrics[mask].copy()

    result = result.sort_values(
        "avg_turnover_5d",
        ascending=False
    )

    return result

def apply_volume_initial_screen(metrics):
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
            -5,
            2,
            inclusive="both"
        )
        &
        (
            metrics["avg_turnover_5d"]
            >= 1_500_000_000
        )
        &
        (
            metrics["volume_ratio_prev"]
            >= 0.8
        )
        &
        metrics["ma25_gap_pct"].between(
            0,
            3,
            inclusive="both"
        )
        &
        metrics["rsi14"].between(
            45,
            55,
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
# ============================================================
# 戦略別 S/A/B/C/D/E 評価
# ============================================================

GRADE_ORDER = ("S", "A", "B", "C", "D", "E")


def _num(row, key, default=None):
    value = row.get(key, default)

    if value is None:
        return default

    try:
        value = float(value)
    except (TypeError, ValueError):
        return default

    if np.isnan(value) or np.isinf(value):
        return default

    return value


def _bool(row, key):
    value = row.get(key, False)

    if value is None:
        return False

    return bool(value)


def _score_to_grade(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"

    return "E"


def _finish_grade(score, flags, reasons, s_required=None):
    score = max(0, min(100, int(round(score))))
    grade = _score_to_grade(score)

    # Sは点数だけでは付けない。
    # 各戦略の必須条件を全部満たした場合だけ許可する。
    if grade == "S" and s_required is not None:
        if not all(s_required):
            grade = "A"

    return {
        "base_grade": grade,
        "strategy_score": score,
        "condition_flags": flags,
        "grade_reasons": reasons,
    }


# ------------------------------------------------------------
# 1. 25MA押し待ち
# ------------------------------------------------------------

def grade_25ma_pullback(row):
    score = 0
    flags = {}
    reasons = []

    gap = _num(row, "ma25_gap_pct")
    vol_prev = _num(row, "volume_ratio_prev")
    vol_20d = _num(row, "volume_ratio_20d")
    rsi = _num(row, "rsi14")

    touched = _bool(row, "touched_ma25")
    recovered = _bool(row, "recovered_ma25")
    ma25_up = row.get("ma25_direction") == "up"

    near_ma25 = (
        gap is not None
        and 0 <= gap <= 3
    )

    strong_near_ma25 = (
        gap is not None
        and 0 <= gap <= 2
    )

    volume_expansion = (
        (vol_prev is not None and vol_prev >= 1.5)
        or
        (vol_20d is not None and vol_20d >= 1.3)
    )

    overheated = (
        rsi is not None
        and rsi >= 75
    )

    flags["touched_ma25"] = touched
    flags["recovered_ma25"] = recovered
    flags["ma25_up"] = ma25_up
    flags["near_ma25"] = near_ma25
    flags["strong_near_ma25"] = strong_near_ma25
    flags["volume_expansion"] = volume_expansion
    flags["overheated"] = overheated

    if touched:
        score += 20
        reasons.append("25MAタッチ")

    if recovered:
        score += 20
        reasons.append("25MA回復")

    if ma25_up:
        score += 20
        reasons.append("25MA上向き")

    if gap is not None:
        if 0 <= gap <= 2:
            score += 20
            reasons.append(
                f"25MA乖離良好 {gap:.2f}%"
            )
        elif 2 < gap <= 3:
            score += 12
            reasons.append(
                f"25MA乖離許容 {gap:.2f}%"
            )
        elif -1 <= gap < 0:
            score += 8
            reasons.append(
                f"25MA直下 {gap:.2f}%"
            )

    if volume_expansion:
        score += 20
        reasons.append("出来高増加")

    if overheated:
        score -= 15
        reasons.append("RSI過熱")

    return _finish_grade(
        score,
        flags,
        reasons,
        s_required=[
            touched,
            recovered,
            ma25_up,
            strong_near_ma25,
            volume_expansion,
            not overheated,
        ],
    )


# ------------------------------------------------------------
# 2. 再加速押し目
# ------------------------------------------------------------

def grade_reacceleration(row):
    score = 0
    flags = {}
    reasons = []

    close = _num(row, "close")
    ma25 = _num(row, "ma25")
    ma75 = _num(row, "ma75")
    gap = _num(row, "ma25_gap_pct")
    vol_prev = _num(row, "volume_ratio_prev")
    rsi = _num(row, "rsi14")

    recovered = _bool(row, "recovered_ma25")
    touched = _bool(row, "touched_ma25")
    ma25_up = row.get("ma25_direction") == "up"

    near_ma25 = (
        gap is not None
        and -1 <= gap <= 3
    )

    above_ma25 = (
        close is not None
        and ma25 is not None
        and close >= ma25
    )

    above_ma75 = (
        close is not None
        and ma75 is not None
        and close >= ma75
    )

    volume_ok = (
        vol_prev is not None
        and vol_prev >= 1.2
    )

    momentum_ok = (
        rsi is not None
        and 48 <= rsi <= 65
    )

    overheated = (
        rsi is not None
        and rsi >= 70
    )

    flags["touched_ma25"] = touched
    flags["recovered_ma25"] = recovered
    flags["ma25_up"] = ma25_up
    flags["near_ma25"] = near_ma25
    flags["above_ma25"] = above_ma25
    flags["above_ma75"] = above_ma75
    flags["volume_ok"] = volume_ok
    flags["momentum_ok"] = momentum_ok
    flags["overheated"] = overheated

    if recovered:
        score += 20
        reasons.append("25MA回復")
    elif touched:
        score += 12
        reasons.append("25MAタッチ")

    if ma25_up:
        score += 20
        reasons.append("25MA上向き")

    if near_ma25:
        score += 15
        reasons.append(
            f"25MA近辺 {gap:.2f}%"
        )

    if above_ma25:
        score += 10
        reasons.append("終値25MA以上")

    if above_ma75:
        score += 10
        reasons.append("終値75MA以上")

    if volume_ok:
        score += 15
        reasons.append(
            f"前日比出来高 {vol_prev:.2f}倍"
        )

    if momentum_ok:
        score += 10
        reasons.append(
            f"RSI {rsi:.1f}"
        )

    if overheated:
        score -= 15
        reasons.append("過熱警戒")

    return _finish_grade(
        score,
        flags,
        reasons,
        s_required=[
            recovered,
            ma25_up,
            near_ma25,
            above_ma25,
            above_ma75,
            volume_ok,
            momentum_ok,
            not overheated,
        ],
    )


# ------------------------------------------------------------
# 3. 初動ブレイク押し待ち
# ------------------------------------------------------------

def grade_initial_breakout(row):
    score = 0
    flags = {}
    reasons = []

    close = _num(row, "close")
    ma25 = _num(row, "ma25")
    ma75 = _num(row, "ma75")
    high20_gap = _num(row, "high20_gap_pct")
    high52_gap = _num(row, "high52_gap_pct")
    vol_prev = _num(row, "volume_ratio_prev")
    rsi = _num(row, "rsi14")

    ma25_up = row.get("ma25_direction") == "up"

    above_ma25 = (
        close is not None
        and ma25 is not None
        and close > ma25
    )

    ma25_above_ma75 = (
        ma25 is not None
        and ma75 is not None
        and ma25 > ma75
    )

    near_high20 = (
        high20_gap is not None
        and -4 <= high20_gap <= 1
    )

    near_high52 = (
        high52_gap is not None
        and -6 <= high52_gap <= 1
    )

    volume_ok = (
        vol_prev is not None
        and vol_prev >= 1.3
    )

    overheated = (
        rsi is not None
        and rsi >= 70
    )

    flags["ma25_up"] = ma25_up
    flags["above_ma25"] = above_ma25
    flags["ma25_above_ma75"] = ma25_above_ma75
    flags["near_high20"] = near_high20
    flags["near_high52"] = near_high52
    flags["volume_ok"] = volume_ok
    flags["overheated"] = overheated

    if near_high20:
        score += 20
        reasons.append(
            f"20日高値接近 {high20_gap:.2f}%"
        )

    if near_high52:
        score += 15
        reasons.append(
            f"52週高値接近 {high52_gap:.2f}%"
        )

    if ma25_up:
        score += 20
        reasons.append("25MA上向き")

    if above_ma25:
        score += 10
        reasons.append("終値25MA以上")

    if ma25_above_ma75:
        score += 15
        reasons.append("25MA > 75MA")

    if volume_ok:
        score += 20
        reasons.append(
            f"前日比出来高 {vol_prev:.2f}倍"
        )

    if overheated:
        score -= 15
        reasons.append("過熱警戒")

    return _finish_grade(
        score,
        flags,
        reasons,
        s_required=[
            near_high20,
            near_high52,
            ma25_up,
            above_ma25,
            ma25_above_ma75,
            volume_ok,
            not overheated,
        ],
    )


# ------------------------------------------------------------
# 4. 出来高初動キャッチ
# ------------------------------------------------------------

def grade_volume_initial(row):
    score = 0
    flags = {}
    reasons = []

    close = _num(row, "close")
    previous_close = _num(
        row,
        "previous_close"
    )
    ma25 = _num(row, "ma25")
    ma75 = _num(row, "ma75")
    vol_prev = _num(
        row,
        "volume_ratio_prev"
    )
    vol_20d = _num(
        row,
        "volume_ratio_20d"
    )
    rsi = _num(row, "rsi14")

    price_up = (
        close is not None
        and previous_close is not None
        and close > previous_close
    )

    ma25_up = (
        row.get("ma25_direction") == "up"
    )

    above_ma25 = (
        close is not None
        and ma25 is not None
        and close >= ma25
    )

    above_ma75 = (
        close is not None
        and ma75 is not None
        and close >= ma75
    )

    strong_volume = (
        (vol_prev is not None and vol_prev >= 1.5)
        or
        (vol_20d is not None and vol_20d >= 1.5)
    )

    volume_ok = (
        (vol_prev is not None and vol_prev >= 1.2)
        or
        (vol_20d is not None and vol_20d >= 1.2)
    )

    overheated = (
        rsi is not None
        and rsi >= 70
    )

    flags["price_up"] = price_up
    flags["ma25_up"] = ma25_up
    flags["above_ma25"] = above_ma25
    flags["above_ma75"] = above_ma75
    flags["volume_ok"] = volume_ok
    flags["strong_volume"] = strong_volume
    flags["overheated"] = overheated

    if strong_volume:
        score += 30
        reasons.append("出来高急増")
    elif volume_ok:
        score += 20
        reasons.append("出来高増加")

    if price_up:
        score += 20
        reasons.append("株価上昇")

    if ma25_up:
        score += 15
        reasons.append("25MA上向き")

    if above_ma25:
        score += 15
        reasons.append("終値25MA以上")

    if above_ma75:
        score += 15
        reasons.append("終値75MA以上")

    if not overheated:
        score += 5
    else:
        score -= 15
        reasons.append("過熱警戒")

    return _finish_grade(
        score,
        flags,
        reasons,
        s_required=[
            strong_volume,
            price_up,
            ma25_up,
            above_ma25,
            above_ma75,
            not overheated,
        ],
    )


# ------------------------------------------------------------
# 共通入口
# ------------------------------------------------------------

def grade_candidate(row, strategy):
    graders = {
        "25MA_pullback":
            grade_25ma_pullback,

        "reacceleration_pullback":
            grade_reacceleration,

        "initial_breakout_pullback":
            grade_initial_breakout,

        "volume_initial_catch":
            grade_volume_initial,
    }

    if strategy not in graders:
        raise ValueError(
            f"Unknown strategy: {strategy}"
        )

    return graders[strategy](row)


def attach_grades(df, strategy):
    if df.empty:
        result = df.copy()

        result["base_grade"] = pd.Series(
            dtype="object"
        )
        result["strategy_score"] = pd.Series(
            dtype="int64"
        )
        result["condition_flags"] = pd.Series(
            dtype="object"
        )
        result["grade_reasons"] = pd.Series(
            dtype="object"
        )

        return result

    rows = []

    for _, row in df.iterrows():
        item = row.to_dict()

        grade_data = grade_candidate(
            item,
            strategy
        )

        item.update(grade_data)
        rows.append(item)

    result = pd.DataFrame(rows)

    grade_rank = {
        "S": 0,
        "A": 1,
        "B": 2,
        "C": 3,
        "D": 4,
        "E": 5,
    }

    result["_grade_rank"] = (
        result["base_grade"]
        .map(grade_rank)
        .fillna(99)
    )

    result = result.sort_values(
        [
            "_grade_rank",
            "strategy_score",
            "avg_turnover_5d",
        ],
        ascending=[
            True,
            False,
            False,
        ],
    )

    result = result.drop(
        columns=["_grade_rank"]
    )

    return result.reset_index(drop=True)
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

    if requested_date is not None:
        delisted_codes = load_delisted_codes(
            requested_date
        )

        before_count = len(universe)

        universe = universe[
            ~universe["code"].isin(delisted_codes)
        ].copy()

        universe = universe.reset_index(drop=True)

        print(
            "Excluded delisted stocks:",
            before_count - len(universe),
        )

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
    # Requested base date must actually exist in enough stocks.
    if requested_date is not None:
        available_count = 0

        for ticker_df in price_data.values():
            if ticker_df is None or ticker_df.empty:
                continue

            dates = pd.to_datetime(
                ticker_df.index
            ).tz_localize(None).normalize()

            if requested_date in dates:
                available_count += 1

        requested_coverage = (
            available_count
            / universe_count
            if universe_count
            else 0.0
        )

        print(
            "Requested date coverage:",
            f"{available_count}/{universe_count}",
            f"({requested_coverage * 100:.2f}%)"
        )

        if requested_coverage < 0.90:
            raise RuntimeError(
                f"Requested base date "
                f"{requested_date.date()} is not ready: "
                f"{available_count}/{universe_count} "
                f"({requested_coverage * 100:.2f}%). "
                f"Do not fall back to previous trading day."
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
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
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
                [
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                ]
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
    reacceleration_result = apply_reacceleration_screen(metrics)
    initial_breakout_result = apply_initial_breakout_screen(metrics)
    volume_initial_result = apply_volume_initial_screen(metrics)
    # 5-2. 戦略別評価を付与
    result = attach_grades(
        result,
        "25MA_pullback"
    )

    reacceleration_result = attach_grades(
        reacceleration_result,
        "reacceleration_pullback"
    )

    initial_breakout_result = attach_grades(
        initial_breakout_result,
        "initial_breakout_pullback"
    )

    volume_initial_result = attach_grades(
        volume_initial_result,
        "volume_initial_catch"
    )
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

    # 全銘柄の指標をJSON保存
    all_metrics_latest = {
        "strategy": "all_metrics",
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
        "results": safe_records(
            metrics
        )
    }

    with open(
        OUTPUT_DIR / "all_metrics.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            make_json_safe(
                all_metrics_latest
            ),
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )
    # 銘柄ごとの個別JSONを保存
    stocks_dir = OUTPUT_DIR / "stocks"

    stocks_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    for record in safe_records(metrics):
        code = str(
            record.get(
                "code",
                ""
            )
        ).strip()

        if not code:
            continue

        stock_data = {
            "strategy": "individual_stock_metrics",
            "base_date": base_date.strftime(
                "%Y-%m-%d"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "code": code,
            "data": record
        }

        with open(
            stocks_dir / f"{code}.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                make_json_safe(
                    stock_data
                ),
                f,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            )
    
    # 全銘柄の指標をJSONでも保存
    all_metrics_latest = {
        "strategy": "all_metrics",
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
        "results": safe_records(
            metrics
        )
    }

    with open(
        OUTPUT_DIR / "all_metrics.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            make_json_safe(
                all_metrics_latest
            ),
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
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
        "eligible_count": len(
            result
        ),
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
            make_json_safe(
                latest
            ),
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    reacceleration_latest = {
        "strategy": "reacceleration_pullback",
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
        "eligible_count": len(
            reacceleration_result
        ),
        "results": safe_records(
            reacceleration_result
        )
    }

    with open(
        OUTPUT_DIR / "reacceleration_latest.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            make_json_safe(
                reacceleration_latest
            ),
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    initial_breakout_latest = {
        "strategy": "initial_breakout_pullback",
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
        "eligible_count": len(
            initial_breakout_result
        ),
        "results": safe_records(
            initial_breakout_result
        )
    }

    with open(
        OUTPUT_DIR / "initial_breakout_latest.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            make_json_safe(
                initial_breakout_latest
            ),
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    volume_initial_latest = {
        "strategy": "volume_initial_catch",
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
        "eligible_count": len(
            volume_initial_result
        ),
        "results": safe_records(
            volume_initial_result
        )
    }

    with open(
        OUTPUT_DIR / "volume_initial_latest.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            make_json_safe(
                volume_initial_latest
            ),
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
            make_json_safe(
                health
            ),
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

    print()
    print(
        "Reacceleration Eligible:",
        len(reacceleration_result)
    )

    if not reacceleration_result.empty:
        print()
        print(
            reacceleration_result[
                [
                    "code",
                    "name",
                    "close",
                    "high52_gap_pct",
                    "avg_turnover_5d",
                    "volume",
                    "previous_volume",
                    "volume_ratio_prev",
                    "ma25_gap_pct",
                    "rsi14",
                ]
            ].to_string(
                index=False
            )
        )
        print()
    print(
        "Initial Breakout Eligible:",
        len(initial_breakout_result)
    )

    if not initial_breakout_result.empty:
        print()
        print(
            initial_breakout_result[
                [
                    "code",
                    "name",
                    "close",
                    "high52_gap_pct",
                    "avg_turnover_5d",
                    "volume",
                    "previous_volume",
                    "volume_ratio_prev",
                    "ma25_gap_pct",
                    "rsi14",
                ]
            ].to_string(
                index=False
            )
        ) 
    print()
    print(
        "Volume Initial Eligible:",
        len(volume_initial_result)
    )

    if not volume_initial_result.empty:
        print()
        print(
            volume_initial_result[
                [
                    "code",
                    "name",
                    "close",
                    "high52_gap_pct",
                    "avg_turnover_5d",
                    "volume",
                    "previous_volume",
                    "volume_ratio_prev",
                    "ma25_gap_pct",
                    "rsi14",
                ]
            ].to_string(
                index=False
            )
        )
        
    debug_codes = [
        "7186",
        "9143",
        "7267",
        "8593",
    ]

    debug_result = metrics[
        metrics["code"].isin(debug_codes)
    ].copy()

    print()
    print("=== Reacceleration Debug ===")

    print(
        debug_result[
            [
                "code",
                "name",
                "close",
                "high52_gap_pct",
                "avg_turnover_5d",
                "volume",
                "previous_volume",
                "volume_ratio_prev",
                "ma25_gap_pct",
                "rsi14",
            ]
        ].to_string(
            index=False
        )
    )
if __name__ == "__main__":
    main()
