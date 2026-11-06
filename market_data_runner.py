
"""
翌東証営業日の寄り付き前に評価するCME市場データランナー。

- 基準日は前東証営業日
- 評価時刻は07:15 JST
- 07:00以前の確定1時間足を使用
- 前CMEセッションの同時刻と比較
- 限月未検証のため参考データとして保存
- 正式評価用market_data.jsonは上書きしない
"""

import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from market_data.providers import fetch_yfinance
from market_data.normalizers import normalize_yfinance
from market_data.validators import validate_freshness


JST = ZoneInfo("Asia/Tokyo")

CME_SYMBOL = "NKD=F"
EVALUATION_TIME = time(7, 15)
PRICE_CUTOFF_TIME = time(7, 0)
MAX_AGE_MINUTES = 180

REFERENCE_OUTPUT = Path(
    "output/market_data_reference_latest.json"
)

REFERENCE_HISTORY = Path(
    "output/market_data_reference_history"
)


def get_tse_calendar():
    return xcals.get_calendar("XTKS")


def is_tse_session(day):
    return bool(
        get_tse_calendar().is_session(
            pd.Timestamp(day.isoformat())
        )
    )


def previous_tse_session(day):
    calendar = get_tse_calendar()
    stamp = pd.Timestamp(day.isoformat())

    if calendar.is_session(stamp):
        stamp = calendar.previous_session(stamp)
    else:
        stamp = calendar.date_to_session(
            stamp,
            direction="previous",
        )

    return stamp.date()


def next_tse_session(day):
    calendar = get_tse_calendar()
    return calendar.next_session(
        pd.Timestamp(day.isoformat())
    ).date()


def get_base_date_and_cutoff():
    now = datetime.now(JST)
    calendar = get_tse_calendar()

    raw = os.getenv("BASE_DATE", "").strip()

    if raw:
        base_date = date.fromisoformat(raw)

        if not is_tse_session(base_date):
            raise RuntimeError(
                f"BASE_DATE is not a TSE session: {base_date}"
            )

        evaluation_date = next_tse_session(base_date)
    else:
        today = now.date()
        stamp = pd.Timestamp(today.isoformat())

        if calendar.is_session(stamp):
            evaluation_date = today
        else:
            evaluation_date = calendar.date_to_session(
                stamp,
                direction="next",
            ).date()

        base_date = previous_tse_session(
            evaluation_date
        )

    cutoff = datetime.combine(
        evaluation_date,
        EVALUATION_TIME,
        tzinfo=JST,
    )

    if now < cutoff:
        raise RuntimeError(
            "Pre-open evaluation time has not arrived: "
            f"now={now.isoformat()}, "
            f"cutoff={cutoff.isoformat()}"
        )

    if (now.date() - base_date).days > 7:
        raise RuntimeError(
            "BASE_DATE is older than 7 days"
        )

    return base_date, cutoff


def get_comparison_cutoffs(evaluation_cutoff):
    """
    朝07:00の確定価格を取得する。
    直近のCME平日取引日と、その前の取引日を選択。

    CMEの祝日・短縮取引はこの関数では
    完全検証できないため、参考データ専用。
    """
    price_cutoff = datetime.combine(
        evaluation_cutoff.date(),
        PRICE_CUTOFF_TIME,
        tzinfo=JST,
    )

    calendar = xcals.get_calendar("CMES")
    candidates = []

    for days_back in range(10):
        candidate = (
            price_cutoff.date()
            - timedelta(days=days_back)
        )

        stamp = pd.Timestamp(candidate.isoformat())

        if calendar.is_session(stamp):
            candidates.append(candidate)

        if len(candidates) == 2:
            break

    if len(candidates) != 2:
        raise RuntimeError(
            "Two CME comparison dates unavailable"
        )

    current_date, previous_date = candidates

    current_cutoff = datetime.combine(
        current_date,
        PRICE_CUTOFF_TIME,
        tzinfo=JST,
    )

    previous_cutoff = datetime.combine(
        previous_date,
        PRICE_CUTOFF_TIME,
        tzinfo=JST,
    )

    return current_cutoff, previous_cutoff


def build_market_data(base_date, evaluation_cutoff):
    current_cutoff, previous_cutoff = (
        get_comparison_cutoffs(evaluation_cutoff)
    )

    hourly = fetch_yfinance(CME_SYMBOL)

    normalized = normalize_yfinance(
        CME_SYMBOL,
        hourly,
        daily_df=None,
        cutoff=current_cutoff,
        previous_session_end=previous_cutoff,
    )

    validated = validate_freshness(
        normalized,
        MAX_AGE_MINUTES,
        now=evaluation_cutoff,
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "CME freshness validation failed: "
            f"{validated.get('reason')}"
        )

    validated["key"] = "nikkei225_futures_cme"
    validated["name"] = "日経225先物（CME）"
    validated["category"] = "futures"
    validated["evaluation_base_date"] = (
        base_date.isoformat()
    )
    validated["evaluation_cutoff_jst"] = (
        evaluation_cutoff.isoformat()
    )
    validated["contract_month_verified"] = False
    validated["usable"] = False
    validated["reference_usable"] = True

    return {
        "base_date": base_date.isoformat(),
        "generated_at_jst": (
            datetime.now(JST).isoformat()
        ),
        "evaluation_status": "reference_only",
        "official_publication_allowed": False,
        "results": [validated],
    }


def write_json_atomic(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_name(path.name + ".tmp")

    try:
        temp.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def main():
    base_date, evaluation_cutoff = (
        get_base_date_and_cutoff()
    )

    print(
        "BASE_DATE:",
        base_date.isoformat(),
    )
    print(
        "EVALUATION_CUTOFF:",
        evaluation_cutoff.isoformat(),
    )

    payload = build_market_data(
        base_date,
        evaluation_cutoff,
    )

    history_path = (
        REFERENCE_HISTORY
        / f"market_data_{base_date.isoformat()}.json"
    )

    write_json_atomic(history_path, payload)
    write_json_atomic(REFERENCE_OUTPUT, payload)

    print(
        "[MARKET DATA REFERENCE READY]",
        base_date.isoformat(),
        flush=True,
    )

    print(
        "[OFFICIAL MARKET DATA]",
        "not published: contract month unverified",
        flush=True,
    )


if __name__ == "__main__":
    main()
