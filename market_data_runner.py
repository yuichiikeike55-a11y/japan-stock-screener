
"""
CME先物データ取得：深夜・前営業日対応版

BASE_DATE は日本株の評価基準日。
CMEは基準日の20:30 JSTまでの観測値を使用する。

・当日20:30前は実行時刻を上限とする
・深夜や休日の前営業日指定を許可
・未来の観測値は使用しない
・鮮度不足や欠損時は公開せず停止
・7日を超える過去日の再取得は停止
"""

import json
import math
import os

from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)
from market_data.normalizers import normalize_yfinance
from market_data.validators import validate_freshness


JST = ZoneInfo("Asia/Tokyo")

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "market_data.json"
HISTORY_DIR = OUTPUT_DIR / "market_data_history"

CME_SYMBOL = "NKD=F"
CME_KEY = "nikkei225_futures_cme"

MAX_AGE_MINUTES = 180
MAX_HISTORY_DAYS = 7


def parse_observation_time(value):
    if not value:
        raise RuntimeError(
            "STOP: CME observation time missing"
        )

    dt = datetime.fromisoformat(str(value))

    if dt.tzinfo is None:
        raise RuntimeError(
            "STOP: CME observation timezone missing"
        )

    return dt.astimezone(JST)


def get_base_date(now_jst):
    text = os.getenv("BASE_DATE", "").strip()

    if not text:
        return now_jst.date()

    return datetime.strptime(
        text, "%Y-%m-%d"
    ).date()


def validate_base_date(base_date, now_jst):
    today = now_jst.date()

    if base_date > today:
        raise RuntimeError(
            "STOP: future BASE_DATE is prohibited"
        )

    if base_date < today - timedelta(
        days=MAX_HISTORY_DAYS
    ):
        raise RuntimeError(
            "STOP: BASE_DATE is too old "
            "for automatic historical retrieval"
        )

    # 土日を日本株の評価日として使わない
    if base_date.weekday() >= 5:
        raise RuntimeError(
            "STOP: BASE_DATE is a weekend. "
            "Use the latest Japanese trading date."
        )


def get_effective_cutoff(base_date, now_jst):
    cutoff = datetime.combine(
        base_date,
        time(20, 30),
        tzinfo=JST,
    )

    return min(cutoff, now_jst)


def validate_change_pct(value):
    if value is None or isinstance(value, bool):
        raise RuntimeError(
            "STOP: CME change_pct missing"
        )

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(
            "STOP: CME change_pct invalid"
        )

    if not math.isfinite(number):
        raise RuntimeError(
            "STOP: CME change_pct not finite"
        )

    return number


def main():
    now_jst = datetime.now(JST)
    base_date = get_base_date(now_jst)

    validate_base_date(
        base_date,
        now_jst,
    )

    effective_cutoff = get_effective_cutoff(
        base_date,
        now_jst,
    )

    print("Action date:", now_jst.isoformat())
    print("Requested base date:", base_date)
    print(
        "CME evaluation cutoff:",
        effective_cutoff.isoformat(),
    )

    # CME先物取得
    print(
        "Fetching CME futures:",
        CME_SYMBOL,
    )

    hourly = fetch_yfinance(CME_SYMBOL)
    daily = fetch_yfinance_daily(CME_SYMBOL)

    normalized = normalize_yfinance(
        CME_SYMBOL,
        hourly,
        daily,
        cutoff=effective_cutoff,
    )

    validated = validate_freshness(
        normalized,
        MAX_AGE_MINUTES,
        now=effective_cutoff,
    )

    print(
        "CME freshness:",
        validated.get("status"),
        validated.get("as_of"),
        validated.get("age_minutes"),
        validated.get("reason"),
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "STOP: CME unavailable or stale "
            f"at evaluation cutoff: "
            f"{validated.get('reason')}"
        )

    as_of_jst = parse_observation_time(
        validated.get("as_of")
    )

    if as_of_jst > effective_cutoff:
        raise RuntimeError(
            "STOP: CME observation is "
            "after evaluation cutoff"
        )

    if as_of_jst > now_jst:
        raise RuntimeError(
            "STOP: future CME observation"
        )

    change_pct = validate_change_pct(
        validated.get("change_pct")
    )

    # 出力
    result = {
        "key": CME_KEY,
        "name": "日経225先物（CME）",
        "category": "futures",
        **validated,
        "change_pct": change_pct,
        "as_of_jst": as_of_jst.isoformat(),
        "evaluation_base_date": (
            base_date.isoformat()
        ),
        "evaluation_cutoff_jst": (
            effective_cutoff.isoformat()
        ),
    }

    output_data = {
        "results": [result]
    }

    snapshot_file = (
        HISTORY_DIR
        / f"market_data_{base_date.isoformat()}.json"
    )

    # 既存の新しいデータを保護
    if snapshot_file.exists():
        existing = json.loads(
            snapshot_file.read_text(
                encoding="utf-8"
            )
        )

        previous = next(
            (
                item
                for item in existing.get(
                    "results", []
                )
                if item.get("key") == CME_KEY
            ),
            None,
        )

        if previous is not None:
            previous_time = parse_observation_time(
                previous.get("as_of")
            )

            if as_of_jst < previous_time:
                raise RuntimeError(
                    "STOP: existing snapshot "
                    "has newer CME observation"
                )

    # すべての検証が通った後に保存
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoded = json.dumps(
        output_data,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )

    snapshot_tmp = snapshot_file.with_suffix(
        ".json.tmp"
    )

    output_tmp = OUTPUT_FILE.with_suffix(
        ".json.tmp"
    )

    snapshot_tmp.write_text(
        encoded,
        encoding="utf-8",
    )

    output_tmp.write_text(
        encoded,
        encoding="utf-8",
    )

    os.replace(
        snapshot_tmp,
        snapshot_file,
    )

    os.replace(
        output_tmp,
        OUTPUT_FILE,
    )

    print(
        "Saved CME snapshot:",
        snapshot_file,
    )

    print(
        "Saved market data:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
