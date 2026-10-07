import os
import json
import time
from io import BytesIO, StringIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
import urllib.request
from bs4 import BeautifulSoup

JST = ZoneInfo("Asia/Tokyo")

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
def get_jpx_holidays():
    url = "https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            html = response.read().decode("utf-8")

        tables = pd.read_html(StringIO(html))
        holidays = set()

        for table in tables:
            for col in table.columns:
                for value in table[col].dropna():
                    try:
                        d = pd.to_datetime(value).date()
                        holidays.add(d)
                    except Exception:
                        pass

        return holidays

    except Exception as e:
        raise RuntimeError(
            "Failed to load JPX holiday calendar: "
            f"{repr(e)}"
        )


def get_previous_trading_date(target_date):
    """
    target_date より前の直近JPX営業日を返す。
    土日・JPX休場日は遡る。
    """
    holidays = get_jpx_holidays()

    d = target_date - timedelta(days=1)

    while (
        d.weekday() >= 5
        or d in holidays
    ):
        d -= timedelta(days=1)

    return d
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

    soup = BeautifulSoup(r.text, "html.parser")

    base_date = pd.Timestamp(base_date).normalize()
    delisted_codes = set()
    parsed_rows = 0

    for tr in soup.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in tr.find_all(["th", "td"])
        ]

        if len(cells) < 3:
            continue

        delisted_date = pd.to_datetime(
            cells[0],
            errors="coerce",
        )
        code = clean_code(cells[2])

        if pd.isna(delisted_date) or code is None:
            continue

        parsed_rows += 1

        delisted_date = pd.Timestamp(
            delisted_date
        ).normalize()

        if delisted_date <= base_date:
            delisted_codes.add(code)

    if parsed_rows == 0:
        raise RuntimeError(
            "JPX delisted-stock rows were not found"
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

    sector17_col = find_column(
        df.columns,
        ["17業種区分"]
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

    if sector17_col is None:
        raise RuntimeError(
            "JPXファイルの17業種区分列を"
            "特定できません。"
        )

    prime = prime[
        [
            "_code",
            name_col,
            market_col,
            sector17_col,
        ]
    ].copy()

    prime.columns = [
        "code",
        "name",
        "market",
        "sector17",
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
            sector17 = lookup.loc[ticker, "sector17"]
        except Exception:
            name = ""
            market = "Prime"
            sector17 = ""

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
            "sector17": str(sector17),
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
# セクター評価 25点
# ============================================================

def score_sector_25(
    sector_row,
    relative_rank=None,
    sector_count=18,
):
    """
    セクター評価：25点満点

    配点
    1. 中期トレンド                 8点
    2. 短中期モメンタム             7点
    3. 高値位置                     4点
    4. 出来高・資金流入             3点
    5. 18セクター内相対順位         3点

    data_quality warning の場合も点数自体は計算するが、
    最終評価側で S/A 禁止（最高B）を適用する。
    """

    if sector_row is None:
        return {
            "sector_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "sector_data_missing",
        }

    # --------------------------------------------------------
    # 必須項目
    # --------------------------------------------------------

    required_keys = [
        "base_date",
        "close",
        "ma25",
        "ma25_direction",
        "ma25_gap_pct",
        "return_1d_pct",
        "return_5d_pct",
        "return_20d_pct",
        "high20_gap_pct",
        "volume_ratio_20d",
    ]

    missing = []

    for key in required_keys:
        value = sector_row.get(key)

        if value is None:
            missing.append(key)

    if missing:
        return {
            "sector_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "sector_required_data_missing",
            "missing_fields": missing,
        }

    # --------------------------------------------------------
    # 数値取得
    # --------------------------------------------------------

    close = _num(
        sector_row,
        "close"
    )

    ma25 = _num(
        sector_row,
        "ma25"
    )

    ma25_gap = _num(
        sector_row,
        "ma25_gap_pct"
    )

    ret1 = _num(
        sector_row,
        "return_1d_pct"
    )

    ret5 = _num(
        sector_row,
        "return_5d_pct"
    )

    ret20 = _num(
        sector_row,
        "return_20d_pct"
    )

    high20_gap = _num(
        sector_row,
        "high20_gap_pct"
    )

    high52_gap = _num(
        sector_row,
        "high52_gap_pct"
    )

    volume_ratio = _num(
        sector_row,
        "volume_ratio_20d"
    )

    ma25_direction = sector_row.get(
        "ma25_direction"
    )

    # --------------------------------------------------------
    # 1. 中期トレンド 8点
    # MA25方向 + 株価位置
    # --------------------------------------------------------

    trend_score = 0

    if ma25_direction == "up":
        trend_score += 4
    elif ma25_direction == "flat":
        trend_score += 2

    if (
        close is not None
        and ma25 is not None
        and close >= ma25
    ):
        trend_score += 4
    elif (
        ma25_gap is not None
        and ma25_gap >= -2
    ):
        trend_score += 2

    trend_score = min(
        trend_score,
        8
    )

    # --------------------------------------------------------
    # 2. 短中期モメンタム 7点
    # 1日 / 5日 / 20日
    # --------------------------------------------------------

    momentum_score = 0

    # 1日：最大1点
    if ret1 > 0:
        momentum_score += 1

    # 5日：最大2点
    if ret5 >= 3:
        momentum_score += 2
    elif ret5 > 0:
        momentum_score += 1

    # 20日：最大4点
    if ret20 >= 8:
        momentum_score += 4
    elif ret20 >= 4:
        momentum_score += 3
    elif ret20 > 0:
        momentum_score += 2
    elif ret20 >= -2:
        momentum_score += 1

    momentum_score = min(
        momentum_score,
        7
    )

    # --------------------------------------------------------
    # 3. 高値位置 4点
    # 20日高値 + 52週高値
    # --------------------------------------------------------

    high_score = 0

    # 20日高値：最大2点
    if high20_gap >= -2:
        high_score += 2
    elif high20_gap >= -5:
        high_score += 1

    # 52週高値：最大2点
    # high52欠損時は加点しない
    if high52_gap is not None:
        if high52_gap >= -5:
            high_score += 2
        elif high52_gap >= -10:
            high_score += 1

    high_score = min(
        high_score,
        4
    )

    # --------------------------------------------------------
    # 4. 出来高・資金流入 3点
    # --------------------------------------------------------

    volume_score = 0

    if volume_ratio >= 1.5:
        volume_score = 3
    elif volume_ratio >= 1.2:
        volume_score = 2
    elif volume_ratio >= 1.0:
        volume_score = 1

    # --------------------------------------------------------
    # 5. 18セクター内相対順位 3点
    # --------------------------------------------------------

    relative_score = 0

    if (
        relative_rank is not None
        and sector_count > 0
    ):
        if relative_rank <= 3:
            relative_score = 3
        elif relative_rank <= 6:
            relative_score = 2
        elif relative_rank <= 9:
            relative_score = 1

    # --------------------------------------------------------
    # 合計
    # --------------------------------------------------------

    total = (
        trend_score
        + momentum_score
        + high_score
        + volume_score
        + relative_score
    )

    total = max(
        0,
        min(
            25,
            int(total)
        )
    )

    quality_status = sector_row.get(
        "data_quality_status",
        "ok"
    )

    quality_flags = sector_row.get(
        "data_quality_flags",
        []
    )

    return {
        "sector_score": total,

        "sector_score_breakdown": {
            "medium_term_trend":
                trend_score,

            "momentum":
                momentum_score,

            "high_position":
                high_score,

            "volume_flow":
                volume_score,

            "relative_rank":
                relative_score,
        },

        "relative_rank":
            relative_rank,

        "sector_count":
            sector_count,

        "sector":
            sector_row.get(
                "sector"
            ),

        "sector_base_date":
            sector_row.get(
                "base_date"
            ),

        "data_quality_status":
            quality_status,

        "data_quality_flags":
            quality_flags,

        "evaluation_status":
            "ok",
    }    
def build_sector_relative_ranks(sector_results):
    """
    18セクターを相対評価して順位を付ける。

    順位判定用スコア：
    ・20日騰落率を中心
    ・5日騰落率
    ・1日騰落率
    ・MA25方向
    ・MA25上の位置
    ・出来高比

    最終的なセクター25点のうち、
    相対順位3点を決めるためだけに使用する。
    """

    if not sector_results:
        return {}

    ranked = []

    for row in sector_results:

        sector = row.get(
            "sector"
        )

        if not sector:
            continue

        ret1 = _num(
            row,
            "return_1d_pct"
        )

        ret5 = _num(
            row,
            "return_5d_pct"
        )

        ret20 = _num(
            row,
            "return_20d_pct"
        )

        ma25_gap = _num(
            row,
            "ma25_gap_pct"
        )

        volume_ratio = _num(
            row,
            "volume_ratio_20d"
        )

        ma25_direction = row.get(
            "ma25_direction"
        )

        # 必須データ不足なら
        # 相対順位の対象外
        if (
            ret1 is None
            or ret5 is None
            or ret20 is None
            or ma25_gap is None
            or volume_ratio is None
        ):
            continue

        # --------------------------------------------
        # 順位判定用内部スコア
        # --------------------------------------------

        rank_score = 0.0

        # 20日モメンタムを最重視
        rank_score += ret20 * 0.50

        # 5日
        rank_score += ret5 * 0.25

        # 1日
        rank_score += ret1 * 0.10

        # MA25方向
        if ma25_direction == "up":
            rank_score += 2.0
        elif ma25_direction == "flat":
            rank_score += 0.5
        elif ma25_direction == "down":
            rank_score -= 1.0

        # MA25より上なら加点
        if ma25_gap >= 0:
            rank_score += 1.0
        elif ma25_gap < -3:
            rank_score -= 1.0

        # 出来高による資金流入
        if volume_ratio >= 1.5:
            rank_score += 1.5
        elif volume_ratio >= 1.2:
            rank_score += 1.0
        elif volume_ratio >= 1.0:
            rank_score += 0.5

        ranked.append(
            {
                "sector": sector,
                "rank_score":
                    float(rank_score),
            }
        )

    ranked.sort(
        key=lambda x: x[
            "rank_score"
        ],
        reverse=True,
    )

    rank_map = {}

    for index, item in enumerate(
        ranked,
        start=1,
    ):
        rank_map[
            item["sector"]
        ] = {
            "rank": index,
            "rank_score":
                item["rank_score"],
        }

    return rank_map
def load_sector_evaluation_data(base_date):
    """
    sector_indices_latest.json を読み込み、
    最終評価に使用できる状態か確認する。

    安全弁：
    ・ファイルなし → 評価停止
    ・18セクター未完 → 評価停止
    ・failureあり → 評価停止
    ・latest_base_date不一致 → 評価停止
    ・各セクターのbase_date不一致 → 評価停止

    data_quality warning はここでは停止しない。
    個別セクター評価後、最終ランクでS/A禁止を適用する。
    """

    sector_path = (
        OUTPUT_DIR
        / "sector_indices_latest.json"
    )

    # --------------------------------------------------------
    # ファイル存在確認
    # --------------------------------------------------------

    if not sector_path.exists():
        return {
            "status": "stopped",
            "reason": "sector_file_missing",
            "path": str(sector_path),
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # JSON読み込み
    # --------------------------------------------------------

    try:
        with open(
            sector_path,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except Exception as e:
        return {
            "status": "stopped",
            "reason": "sector_json_load_failed",
            "error": str(e),
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # 基準日
    # --------------------------------------------------------

    if isinstance(
        base_date,
        pd.Timestamp,
    ):
        expected_date = (
            base_date.strftime(
                "%Y-%m-%d"
            )
        )
    else:
        expected_date = str(
            base_date
        )

    latest_base_date = data.get(
        "latest_base_date"
    )

    if latest_base_date != expected_date:
        return {
            "status": "stopped",
            "reason": "sector_base_date_mismatch",
            "expected_base_date":
                expected_date,
            "sector_base_date":
                latest_base_date,
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # 完全性チェック
    # --------------------------------------------------------

    results = data.get(
        "results",
        []
    )

    sector_count = data.get(
        "sector_count"
    )

    processed_count = data.get(
        "processed_count"
    )

    failure_count = data.get(
        "failure_count",
        0
    )

    if (
        sector_count != 18
        or processed_count != 18
        or len(results) != 18
        or failure_count != 0
    ):
        return {
            "status": "stopped",
            "reason": "sector_data_incomplete",
            "sector_count":
                sector_count,
            "processed_count":
                processed_count,
            "result_count":
                len(results),
            "failure_count":
                failure_count,
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # 各セクターの日付も確認
    # --------------------------------------------------------

    wrong_dates = []

    for row in results:

        row_date = row.get(
            "base_date"
        )

        if row_date != expected_date:
            wrong_dates.append(
                {
                    "sector":
                        row.get(
                            "sector"
                        ),
                    "base_date":
                        row_date,
                }
            )

    if wrong_dates:
        return {
            "status": "stopped",
            "reason": "sector_individual_base_date_mismatch",
            "expected_base_date":
                expected_date,
            "wrong_dates":
                wrong_dates,
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # セクター名重複チェック
    # --------------------------------------------------------

    sector_names = [
        row.get("sector")
        for row in results
    ]

    if (
        any(
            name is None
            for name in sector_names
        )
        or len(set(sector_names)) != 18
    ):
        return {
            "status": "stopped",
            "reason": "sector_name_invalid_or_duplicate",
            "results": [],
            "rank_map": {},
        }

    # --------------------------------------------------------
    # 相対順位作成
    # --------------------------------------------------------

    rank_map = (
        build_sector_relative_ranks(
            results
        )
    )

    # 必須データ不足などで
    # 18セクター全部を順位付けできなければ停止
    if len(rank_map) != 18:
        return {
            "status": "stopped",
            "reason": "sector_relative_rank_incomplete",
            "ranked_sector_count":
                len(rank_map),
            "results": [],
            "rank_map": rank_map,
        }

    # --------------------------------------------------------
    # 正常
    # --------------------------------------------------------

    return {
        "status": "ok",
        "reason": None,
        "base_date":
            expected_date,
        "sector_count": 18,
        "results": results,
        "rank_map": rank_map,
    }    
def normalize_sector17_name(sector17):
    """
    JPXの17業種区分名を、
    sector_indices_latest.json の
    セクター名へ正規化する。

    基本的にはTOPIX-17と同名なので、
    表記ゆれだけ吸収する。
    """

    if sector17 is None:
        return None

    name = str(
        sector17
    ).strip()

    if not name:
        return None

    mapping = {
        "食品":
            "食品",

        "エネルギー資源":
            "エネルギー資源",

        "建設・資材":
            "建設・資材",

        "素材・化学":
            "素材・化学",

        "医薬品":
            "医薬品",

        "自動車・輸送機":
            "自動車・輸送機",

        "鉄鋼・非鉄":
            "鉄鋼・非鉄",

        "機械":
            "機械",

        "電機・精密":
            "電機・精密",

        "情報通信・サービスその他":
            "情報通信・サービスその他",

        "電力・ガス":
            "電力・ガス",

        "運輸・物流":
            "運輸・物流",

        "商社・卸売":
            "商社・卸売",

        "小売":
            "小売",

        "銀行":
            "銀行",

        "金融（除く銀行）":
            "金融",

        "金融(除く銀行)":
            "金融",

        "金融":
            "金融",

        "不動産":
            "不動産",
    }

    return mapping.get(
        name
    )    
def attach_sector_scores_to_hits(
    strategy_hits,
    sector_data,
):
    """
    4戦略ヒット銘柄にセクター評価25点を付与する。

    安全弁：
    ・セクターデータ全体が使用不可 → 全銘柄評価停止
    ・銘柄のsector17欠損 → その銘柄を評価停止
    ・対応セクターなし → その銘柄を評価停止
    ・個別セクター必須データ欠損 → その銘柄を評価停止

    半導体への個別割当は現時点では行わない。
    個別銘柄はJPX 17業種を使用する。
    """

    if not strategy_hits:
        return []

    # --------------------------------------------------------
    # セクターデータ全体の安全確認
    # --------------------------------------------------------

    if (
        sector_data is None
        or sector_data.get("status") != "ok"
    ):
        reason = (
            sector_data.get(
                "reason",
                "sector_data_unavailable",
            )
            if sector_data
            else "sector_data_unavailable"
        )

        for stock in strategy_hits:
            stock["sector_evaluation"] = {
                "evaluation_status":
                    "stopped",

                "stop_reason":
                    reason,

                "sector_score":
                    None,
            }

        return strategy_hits

    sector_results = sector_data.get(
        "results",
        []
    )

    rank_map = sector_data.get(
        "rank_map",
        {}
    )

    # --------------------------------------------------------
    # セクター名 → データ
    # --------------------------------------------------------

    sector_lookup = {}

    for row in sector_results:

        sector_name = row.get(
            "sector"
        )

        if sector_name:
            sector_lookup[
                sector_name
            ] = row

    # --------------------------------------------------------
    # 各ヒット銘柄へ付与
    # --------------------------------------------------------

    for stock in strategy_hits:

        metrics = stock.get(
            "metrics",
            {}
        )

        sector17 = metrics.get(
            "sector17"
        )

        normalized_sector = (
            normalize_sector17_name(
                sector17
            )
        )

        # JPX 17業種が取得できない
        if normalized_sector is None:

            stock[
                "sector_evaluation"
            ] = {
                "evaluation_status":
                    "stopped",

                "stop_reason":
                    "stock_sector17_missing_or_unknown",

                "sector17":
                    sector17,

                "sector_score":
                    None,
            }

            continue

        # 対応するセクター指数がない
        sector_row = sector_lookup.get(
            normalized_sector
        )

        if sector_row is None:

            stock[
                "sector_evaluation"
            ] = {
                "evaluation_status":
                    "stopped",

                "stop_reason":
                    "sector_index_not_found",

                "sector17":
                    sector17,

                "normalized_sector":
                    normalized_sector,

                "sector_score":
                    None,
            }

            continue

        # ----------------------------------------------------
        # 相対順位
        # ----------------------------------------------------

        rank_info = rank_map.get(
            normalized_sector,
            {}
        )

        relative_rank = rank_info.get(
            "rank"
        )

        # ----------------------------------------------------
        # 25点評価
        # ----------------------------------------------------

        evaluation = score_sector_25(
            sector_row,
            relative_rank=
                relative_rank,
            sector_count=18,
        )

        # ----------------------------------------------------
        # 銘柄側情報も追加
        # ----------------------------------------------------

        evaluation[
            "sector17"
        ] = sector17

        evaluation[
            "normalized_sector"
        ] = normalized_sector

        evaluation[
            "sector_rank_score"
        ] = rank_info.get(
            "rank_score"
        )

        # 半導体独立指数は順位には参加するが、
        # 現時点では個別銘柄へ直接割り当てない
        evaluation[
            "semiconductor_override"
        ] = False

        stock[
            "sector_evaluation"
        ] = evaluation

    return strategy_hits    
# ============================================================
# 戦略適合度 35点
# ============================================================

def score_strategy_fit_35(
    strategy_hit,
):
    """
    既存の各戦略 strategy_score（0～100）を、
    正式評価の戦略適合度35点へ変換する。

    既存 grade_*() が各戦略固有条件を評価済みなので、
    ここでは同じ条件を再実装せず正規化する。

    戦略否定条件による上限C・見送り判定は、
    最終評価の安全弁で別途適用する。
    """

    if strategy_hit is None:
        return {
            "strategy_fit_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "strategy_hit_missing",
        }

    strategy = strategy_hit.get(
        "strategy"
    )

    raw_score = strategy_hit.get(
        "strategy_score_raw"
    )

    if strategy is None:
        return {
            "strategy_fit_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "strategy_name_missing",
        }

    if raw_score is None:
        return {
            "strategy_fit_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "strategy_score_missing",
            "strategy": strategy,
        }

    try:
        raw_score = float(
            raw_score
        )

    except (
        TypeError,
        ValueError,
    ):
        return {
            "strategy_fit_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "strategy_score_invalid",
            "strategy": strategy,
        }

    if (
        np.isnan(raw_score)
        or np.isinf(raw_score)
    ):
        return {
            "strategy_fit_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "strategy_score_invalid",
            "strategy": strategy,
        }

    # --------------------------------------------
    # 0～100 → 0～35
    # --------------------------------------------

    raw_score = max(
        0.0,
        min(
            100.0,
            raw_score,
        ),
    )

    score_35 = (
        raw_score
        / 100.0
        * 35.0
    )

    # 0.1点単位
    score_35 = round(
        score_35,
        1,
    )

    return {
        "strategy":
            strategy,

        "strategy_fit_score":
            score_35,

        "strategy_score_raw":
            raw_score,

        "base_grade_raw":
            strategy_hit.get(
                "base_grade_raw"
            ),

        "condition_flags":
            strategy_hit.get(
                "condition_flags",
                {}
            ),

        "grade_reasons":
            strategy_hit.get(
                "grade_reasons",
                []
            ),

        "evaluation_status":
            "ok",

        "stop_reason":
            None,
    }
def attach_strategy_fit_scores(
    strategy_hits,
):
    """
    4戦略ヒット銘柄について、
    各戦略を35点満点で評価する。

    ・各戦略を個別採点
    ・最高点の戦略を主戦略
    ・その他を副戦略
    ・複数戦略ヒット情報を保持

    複数一致ボーナスは、
    最終100点計算時に別途加算する。
    """

    if not strategy_hits:
        return []

    for stock in strategy_hits:

        hits = stock.get(
            "strategy_hits",
            []
        )

        if not hits:
            stock[
                "strategy_fit_evaluation"
            ] = {
                "evaluation_status":
                    "stopped",

                "stop_reason":
                    "strategy_hits_missing",

                "strategy_fit_score":
                    None,
            }

            continue

        # --------------------------------------------
        # 各戦略を35点評価
        # --------------------------------------------

        evaluated_hits = []

        for hit in hits:

            evaluation = (
                score_strategy_fit_35(
                    hit
                )
            )

            evaluated_hit = dict(
                hit
            )

            evaluated_hit[
                "strategy_fit_evaluation"
            ] = evaluation

            evaluated_hits.append(
                evaluated_hit
            )

        # --------------------------------------------
        # 正常評価できた戦略だけ抽出
        # --------------------------------------------

        valid_hits = [
            hit
            for hit in evaluated_hits
            if (
                hit.get(
                    "strategy_fit_evaluation",
                    {}
                ).get(
                    "evaluation_status"
                )
                == "ok"
            )
        ]

        if not valid_hits:

            stock[
                "strategy_hits"
            ] = evaluated_hits

            stock[
                "strategy_fit_evaluation"
            ] = {
                "evaluation_status":
                    "stopped",

                "stop_reason":
                    "no_valid_strategy_score",

                "strategy_fit_score":
                    None,
            }

            continue

        # --------------------------------------------
        # 35点が高い順
        # --------------------------------------------

        valid_hits.sort(
            key=lambda x: (
                x[
                    "strategy_fit_evaluation"
                ].get(
                    "strategy_fit_score",
                    -1,
                )
            ),
            reverse=True,
        )

        # --------------------------------------------
        # 主戦略
        # --------------------------------------------

        primary_hit = (
            valid_hits[0]
        )

        primary_strategy = (
            primary_hit.get(
                "strategy"
            )
        )

        primary_score = (
            primary_hit[
                "strategy_fit_evaluation"
            ].get(
                "strategy_fit_score"
            )
        )

        # --------------------------------------------
        # 副戦略
        # --------------------------------------------

        secondary_strategies = [
            hit.get(
                "strategy"
            )
            for hit in valid_hits[1:]
        ]

        # --------------------------------------------
        # 銘柄へ保存
        # --------------------------------------------

        stock[
            "strategy_hits"
        ] = evaluated_hits

        stock[
            "primary_strategy"
        ] = primary_strategy

        stock[
            "secondary_strategies"
        ] = secondary_strategies

        stock[
            "strategy_fit_evaluation"
        ] = {
            "evaluation_status":
                "ok",

            "stop_reason":
                None,

            "strategy_fit_score":
                primary_score,

            "primary_strategy":
                primary_strategy,

            "secondary_strategies":
                secondary_strategies,

            "evaluated_strategy_count":
                len(valid_hits),

            "hit_count":
                len(hits),
        }

    return strategy_hits    
# ============================================================
# 個別テクニカル 15点
# ============================================================

def score_stock_technical_15(
    metrics,
):
    """
    個別テクニカル：15点満点

    1. 中期トレンド     6点
    2. モメンタム       5点
    3. 高値位置         4点

    出来高・需給は別枠10点で評価するため、
    ここでは採点しない。
    """

    if not metrics:
        return {
            "technical_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "stock_metrics_missing",
        }

    # --------------------------------------------------------
    # 必須データ
    # --------------------------------------------------------

    required_keys = [
        "close",
        "ma25",
        "ma75",
        "ma25_gap_pct",
        "rsi14",
        "high52_gap_pct",
    ]

    missing = []

    for key in required_keys:

        value = metrics.get(
            key
        )

        if value is None:
            missing.append(
                key
            )

    if missing:
        return {
            "technical_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "technical_required_data_missing",
            "missing_fields": missing,
        }

    # --------------------------------------------------------
    # 数値取得
    # --------------------------------------------------------

    close = _num(
        metrics,
        "close"
    )

    ma25 = _num(
        metrics,
        "ma25"
    )

    ma75 = _num(
        metrics,
        "ma75"
    )

    ma25_gap = _num(
        metrics,
        "ma25_gap_pct"
    )

    rsi14 = _num(
        metrics,
        "rsi14"
    )

    high52_gap = _num(
        metrics,
        "high52_gap_pct"
    )

    # 数値化失敗
    numeric_values = [
        close,
        ma25,
        ma75,
        ma25_gap,
        rsi14,
        high52_gap,
    ]

    if any(
        value is None
        for value in numeric_values
    ):
        return {
            "technical_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "technical_numeric_data_invalid",
        }

    # --------------------------------------------------------
    # 1. 中期トレンド 6点
    # --------------------------------------------------------

    trend_score = 0

    # 株価 > 25MA
    if close >= ma25:
        trend_score += 2

    # 25MA > 75MA
    if ma25 >= ma75:
        trend_score += 2

    # 25MAからの位置
    # 過度な上方乖離は満点にしない
    if 0 <= ma25_gap <= 5:
        trend_score += 2

    elif -2 <= ma25_gap < 0:
        trend_score += 1

    elif 5 < ma25_gap <= 8:
        trend_score += 1

    trend_score = min(
        trend_score,
        6,
    )

    # --------------------------------------------------------
    # 2. モメンタム 5点
    # RSI14
    # --------------------------------------------------------

    momentum_score = 0

    # 強いが過熱しすぎていない
    if 55 <= rsi14 <= 70:
        momentum_score = 5

    elif 50 <= rsi14 < 55:
        momentum_score = 4

    elif 45 <= rsi14 < 50:
        momentum_score = 3

    elif 40 <= rsi14 < 45:
        momentum_score = 2

    elif 30 <= rsi14 < 40:
        momentum_score = 1

    # RSI70超は上昇力はあるが
    # 過熱リスクを考慮
    elif 70 < rsi14 <= 75:
        momentum_score = 4

    elif 75 < rsi14 <= 80:
        momentum_score = 2

    elif rsi14 > 80:
        momentum_score = 0

    # --------------------------------------------------------
    # 3. 高値位置 4点
    # 52週高値からの距離
    # --------------------------------------------------------

    high_score = 0

    if high52_gap >= -3:
        high_score = 4

    elif high52_gap >= -7:
        high_score = 3

    elif high52_gap >= -12:
        high_score = 2

    elif high52_gap >= -20:
        high_score = 1

    # --------------------------------------------------------
    # 合計
    # --------------------------------------------------------

    total = (
        trend_score
        + momentum_score
        + high_score
    )

    total = max(
        0,
        min(
            15,
            int(total),
        ),
    )

    return {
        "technical_score":
            total,

        "technical_score_breakdown": {
            "medium_term_trend":
                trend_score,

            "momentum":
                momentum_score,

            "high_position":
                high_score,
        },

        "evaluation_status":
            "ok",

        "stop_reason":
            None,
    }
def attach_technical_scores(
    strategy_hits,
):
    """
    4戦略ヒット銘柄に
    個別テクニカル15点を付与する。
    """

    if not strategy_hits:
        return []

    for stock in strategy_hits:

        metrics = stock.get(
            "metrics",
            {}
        )

        evaluation = (
            score_stock_technical_15(
                metrics
            )
        )

        stock[
            "technical_evaluation"
        ] = evaluation

    return strategy_hits    

# ============================================================
# 4戦略ヒット銘柄 統合
# ============================================================

def build_strategy_hits(
    result,
    reacceleration_result,
    initial_breakout_result,
    volume_initial_result,
):
    """
    4戦略で実際にヒットした銘柄だけを統合する。

    同一銘柄が複数戦略にヒットした場合も、
    strategy_hits にすべて保持する。

    この関数ではまだ最終100点評価は行わない。
    """

    strategy_frames = [
        (
            "25MA_pullback",
            result,
        ),
        (
            "reacceleration_pullback",
            reacceleration_result,
        ),
        (
            "initial_breakout_pullback",
            initial_breakout_result,
        ),
        (
            "volume_initial_catch",
            volume_initial_result,
        ),
    ]

    stock_map = {}

    for strategy, df in strategy_frames:

        if df is None or df.empty:
            continue

        for _, row in df.iterrows():

            item = row.to_dict()

            code = str(
                item.get(
                    "code",
                    ""
                )
            ).strip()

            if not code:
                continue

            if code not in stock_map:

                stock_map[code] = {
                    "code": code,
                    "name": item.get(
                        "name",
                        ""
                    ),
                    "base_date": item.get(
                        "base_date"
                    ),

                    # 個別指標は元データを保持
                    "metrics": {
                        key: value
                        for key, value
                        in item.items()
                        if key not in {
                            "base_grade",
                            "strategy_score",
                            "condition_flags",
                            "grade_reasons",
                        }
                    },

                    # ヒットした戦略をすべて保存
                    "strategy_hits": [],
                }

            stock_map[
                code
            ][
                "strategy_hits"
            ].append(
                {
                    "strategy":
                        strategy,

                    "strategy_score_raw":
                        item.get(
                            "strategy_score"
                        ),

                    "base_grade_raw":
                        item.get(
                            "base_grade"
                        ),

                    "condition_flags":
                        item.get(
                            "condition_flags",
                            {}
                        ),

                    "grade_reasons":
                        item.get(
                            "grade_reasons",
                            []
                        ),
                }
            )

    results = []

    for code, stock in stock_map.items():

        hits = stock[
            "strategy_hits"
        ]

        # 現時点では既存strategy_scoreが
        # 最も高いものを仮の主戦略とする。
        # 最終100点評価時に正式決定する。
        hits = sorted(
            hits,
            key=lambda x: (
                x.get(
                    "strategy_score_raw"
                )
                if x.get(
                    "strategy_score_raw"
                ) is not None
                else -1
            ),
            reverse=True,
        )

        stock[
            "strategy_hits"
        ] = hits

        stock[
            "hit_count"
        ] = len(hits)

        stock[
            "hit_strategies"
        ] = [
            x["strategy"]
            for x in hits
        ]

        stock[
            "primary_strategy_raw"
        ] = (
            hits[0]["strategy"]
            if hits
            else None
        )

        stock[
            "secondary_strategies_raw"
        ] = [
            x["strategy"]
            for x in hits[1:]
        ]

        results.append(
            stock
        )

    results.sort(
        key=lambda x: (
            -x[
                "hit_count"
            ],
            -(
                x[
                    "strategy_hits"
                ][0].get(
                    "strategy_score_raw"
                )
                or 0
            ),
            x[
                "code"
            ],
        )
    )

    return results    
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
def get_jpx_holidays():
    from io import StringIO

    url = "https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            html = response.read().decode("utf-8")

        tables = pd.read_html(StringIO(html))
        holidays = set()

        for table in tables:
            for col in table.columns:
                for value in table[col].dropna():
                    try:
                        d = pd.to_datetime(value).date()
                        holidays.add(d)
                    except Exception:
                        pass

        return holidays

    except Exception as e:
        raise RuntimeError(
            "Failed to load JPX holiday calendar: "
            f"{repr(e)}"
        )
def get_latest_trading_date(now):
    d = now.date()
    holidays = get_jpx_holidays()

    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)

    return d
    
def get_previous_trading_date(target_date):
    """
    target_date より前の直近JPX営業日を返す。
    土日・JPX休場日は遡る。
    """
    holidays = get_jpx_holidays()

    d = target_date - timedelta(days=1)

    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)

    return d

def main():
    print("=== Japan Stock 25MA Screener ===")

    requested_date_raw = os.getenv(
        "BASE_DATE",
        ""
    ).strip()

    if requested_date_raw:
        action_date = pd.Timestamp(
            requested_date_raw
        ).normalize()

        previous_trading_date = get_previous_trading_date(
            action_date.date()
        )

        requested_date = pd.Timestamp(
            previous_trading_date
        ).normalize()

        print(
            "Action date:",
            action_date.date()
        )

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
    now = datetime.now(JST)
    expected_latest_date = get_latest_trading_date(now)

    print(
        "Expected latest trading date:",
        expected_latest_date
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
    # ========================================================
    # 4戦略ヒット銘柄を統合
    # ========================================================

    strategy_hits = build_strategy_hits(
        result,
        reacceleration_result,
        initial_breakout_result,
        volume_initial_result,
    )
    # ========================================================
    # 戦略適合度 35点
    # ========================================================

    strategy_hits = (
        attach_strategy_fit_scores(
            strategy_hits
        )
    )

    print()
    print(
        "=== STRATEGY FIT SCORES ==="
    )

    for stock in strategy_hits:

        strategy_eval = stock.get(
            "strategy_fit_evaluation",
            {}
        )

        print(
            stock.get("code"),
            stock.get("name"),
            "primary:",
            strategy_eval.get(
                "primary_strategy"
            ),
            "score:",
            strategy_eval.get(
                "strategy_fit_score"
            ),
            "/35",
            "secondary:",
            strategy_eval.get(
                "secondary_strategies"
            ),
            "status:",
            strategy_eval.get(
                "evaluation_status"
            ),
        )    
    # ========================================================
    # 個別テクニカル 15点
    # ========================================================

    strategy_hits = (
        attach_technical_scores(
            strategy_hits
        )
    )

    print()
    print(
        "=== TECHNICAL SCORES ==="
    )

    for stock in strategy_hits:

        technical_eval = stock.get(
            "technical_evaluation",
            {}
        )

        breakdown = technical_eval.get(
            "technical_score_breakdown",
            {}
        )

        print(
            stock.get("code"),
            stock.get("name"),
            "score:",
            technical_eval.get(
                "technical_score"
            ),
            "/15",
            "trend:",
            breakdown.get(
                "medium_term_trend"
            ),
            "/6",
            "momentum:",
            breakdown.get(
                "momentum"
            ),
            "/5",
            "high:",
            breakdown.get(
                "high_position"
            ),
            "/4",
            "status:",
            technical_eval.get(
                "evaluation_status"
            ),
        )    
    # ========================================================
    # セクター評価データ読み込み
    # ========================================================

    sector_evaluation_data = (
        load_sector_evaluation_data(
            base_date
        )
    )

    print()
    print(
        "=== SECTOR EVALUATION DATA ==="
    )

    print(
        "Status:",
        sector_evaluation_data.get(
            "status"
        ),
    )

    print(
        "Reason:",
        sector_evaluation_data.get(
            "reason"
        ),
    )

    if (
        sector_evaluation_data.get(
            "status"
        )
        == "ok"
    ):
        print(
            "Base date:",
            sector_evaluation_data.get(
                "base_date"
            ),
        )

        print(
            "Sector count:",
            sector_evaluation_data.get(
                "sector_count"
            ),
        )

    # ========================================================
    # 4戦略ヒット銘柄へセクター25点を付与
    # ========================================================

    strategy_hits = (
        attach_sector_scores_to_hits(
            strategy_hits,
            sector_evaluation_data,
        )
    )

    print()
    print(
        "=== SECTOR SCORES ==="
    )

    for stock in strategy_hits:

        sector_eval = stock.get(
            "sector_evaluation",
            {}
        )

        print(
            stock.get("code"),
            stock.get("name"),
            "sector:",
            sector_eval.get(
                "normalized_sector"
            ),
            "rank:",
            sector_eval.get(
                "relative_rank"
            ),
            "score:",
            sector_eval.get(
                "sector_score"
            ),
            "status:",
            sector_eval.get(
                "evaluation_status"
            ),
        )    

    strategy_hits_json = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "base_date": (
            base_date.strftime("%Y-%m-%d")
            if base_date is not None
            else None
        ),

        "strategy_count": 4,

        "unique_stock_count": len(
            strategy_hits
        ),

        "results": make_json_safe(
            strategy_hits
        ),
    }

    strategy_hits_path = (
        OUTPUT_DIR
        / "strategy_hits_latest.json"
    )

    with open(
        strategy_hits_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            strategy_hits_json,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print()
    print(
        "=== 4 STRATEGY HITS ==="
    )
    print(
        "Unique stocks:",
        len(strategy_hits),
    )
    print(
        "Saved:",
        strategy_hits_path,
    )

    for stock in strategy_hits:
        print(
            stock["code"],
            stock["name"],
            "hits:",
            stock["hit_count"],
            stock["hit_strategies"],
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
