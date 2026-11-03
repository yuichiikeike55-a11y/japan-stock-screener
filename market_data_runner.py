
"""
翌東証営業日の寄り付き前に評価する市場データランナー。

正式評価条件:
- 東証の直近取引終了済み営業日を基準日とする
- 翌東証営業日の08:45 JSTを評価時刻とする
- CMEの確定済み1時間足のみ利用
- CMEセッション・日足の対応が未検証なら停止
- 正常データのみ最新JSONへ公開
"""

import json
import math
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)
from market_data.normalizers import normalize_yfinance
from market_data.validators import validate_freshness
from market_data.cme_calendar import get_verified_session_end

JST = ZoneInfo("Asia/Tokyo")
EASTERN = ZoneInfo("America/New_York")

OUTPUT = Path("output/market_data.json")
HISTORY_DIR = Path("output/market_data_history")

CME_SYMBOL = "NKD=F"
MAX_AGE_MINUTES = 180
EVALUATION_TIME = time(8, 45)


def get_tse_calendar():
    return xcals.get_calendar("XTKS")


def is_tse_session(day):
    calendar = get_tse_calendar()
    return bool(
        calendar.is_session(
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
    stamp = pd.Timestamp(day.isoformat())

    return calendar.next_session(stamp).date()


def get_base_date_and_cutoff():
    now = datetime.now(JST)

    raw = os.getenv("BASE_DATE", "").strip()

    if raw:
        base_date = date.fromisoformat(raw)

        if not is_tse_session(base_date):
            raise RuntimeError(
                f"BASE_DATE is not a TSE session: {base_date}"
            )
    else:
        base_date = previous_tse_session(now.date())

    next_session = next_tse_session(base_date)

    cutoff = datetime.combine(
        next_session,
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


def get_cme_session_date(cutoff):
    """
    評価時刻までに終了したCMEセッションを探す。

    CMEの取引日と東証の基準日は別々に管理する。
    """
    candidate = cutoff.astimezone(EASTERN).date()

    for days_back in range(8):
        session_date = candidate - timedelta(
            days=days_back
        )

        try:
            session_end = get_verified_session_end(
                session_date
            )
        except Exception:
            continue

        if session_end <= cutoff:
            return session_date, session_end

    raise RuntimeError(
        "No verified CME session before cutoff"
    )


def build_market_data(base_date, cutoff):
    cme_date, cme_end = get_cme_session_date(
        cutoff
    )

    hourly = fetch_yfinance(CME_SYMBOL)
    daily = fetch_yfinance_daily(CME_SYMBOL)

    if daily is None or daily.empty:
        raise RuntimeError("CME daily data missing")

    latest_daily_date = daily.index[-1].date()

    if latest_daily_date != cme_date:
        raise RuntimeError(
            "CME daily session mismatch: "
            f"expected={cme_date}, "
            f"actual={latest_daily_date}"
        )

    normalized = normalize_yfinance(
        CME_SYMBOL,
        hourly,
        daily,
        cutoff=cme_end,
    )

    validated = validate_freshness(
        normalized,
        MAX_AGE_MINUTES,
        now=cme_end,
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "CME freshness validation failed: "
            f"{validated.get('reason')}"
        )

    as_of = datetime.fromisoformat(
        validated["as_of"]
    ).astimezone(JST)

    if as_of > cme_end:
        raise RuntimeError(
            "CME quote after session end"
        )

    change = validated.get("change_pct")

    if (
        not isinstance(change, (int, float))
        or isinstance(change, bool)
        or not math.isfinite(change)
    ):
        raise RuntimeError(
            "CME change_pct invalid"
        )

    result = {
        **validated,
        "key": "nikkei225_futures_cme",
        "name": "日経225先物（CME）",
        "category": "futures",
        "usable": True,
        "evaluation_base_date": base_date.isoformat(),
        "evaluation_cutoff_jst": cutoff.isoformat(),
        "cme_session_date": cme_date.isoformat(),
        "cme_session_end_jst": cme_end.isoformat(),
    }

    return {
        "base_date": base_date.isoformat(),
        "generated_at_jst": datetime.now(
            JST
        ).isoformat(),
        "evaluation_status": "ok",
        "results": [result],
    }


def write_json_atomic(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_name(
        path.name + ".tmp"
    )

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
    base_date, cutoff = (
        get_base_date_and_cutoff()
    )

    print(
        "BASE_DATE:",
        base_date.isoformat(),
    )
    print(
        "EVALUATION_CUTOFF:",
        cutoff.isoformat(),
    )

    payload = build_market_data(
        base_date,
        cutoff,
    )

    history_path = (
        HISTORY_DIR
        / f"market_data_{base_date.isoformat()}.json"
    )

    write_json_atomic(
        history_path,
        payload,
    )
    write_json_atomic(
        OUTPUT,
        payload,
    )

    print(
        "MARKET DATA STATUS:",
        payload["evaluation_status"],
    )
    print(
        "MARKET DATA READY:",
        base_date.isoformat(),
    )


if __name__ == "__main__":
    main()
