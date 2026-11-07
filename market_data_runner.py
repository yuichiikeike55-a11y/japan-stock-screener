
import json
import math
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

EVALUATION_TIME = time(7, 0)
PRICE_CUTOFF_TIME = time(7, 0)
MAX_AGE_MINUTES = 180

OFFICIAL_OUTPUT = Path("output/market_data.json")
REFERENCE_OUTPUT = Path(
    "output/market_data_reference_latest.json"
)

NOTE = (
    "CME continuous futures data used. "
    "Individual contract month not verified; "
    "rollover may affect price comparison. "
    "Annotation only; no score or rank penalty."
)


def calendar():
    return xcals.get_calendar("XTKS")


def is_session(day):
    return bool(
        calendar().is_session(pd.Timestamp(day))
    )


def previous_session(day):
    cal = calendar()
    stamp = pd.Timestamp(day)

    if cal.is_session(stamp):
        return cal.previous_session(stamp).date()

    return cal.date_to_session(
        stamp, direction="previous"
    ).date()


def next_session(day):
    return calendar().next_session(
        pd.Timestamp(day)
    ).date()


def get_dates():
    now = datetime.now(JST)
    manual = os.getenv("BASE_DATE", "").strip()

    if manual:
        base_date = date.fromisoformat(manual)

        if not is_session(base_date):
            raise RuntimeError(
                "STOP: BASE_DATE is not TSE session"
            )

        evaluation_date = base_date + timedelta(days=1)
    else:
        today = now.date()

        if is_session(today):
            evaluation_date = today
        else:
            evaluation_date = calendar().date_to_session(
                pd.Timestamp(today),
                direction="next",
            ).date()

        base_date = previous_session(evaluation_date)

    cutoff = datetime.combine(
        evaluation_date,
        EVALUATION_TIME,
        tzinfo=JST,
    )

    if now < cutoff:
        raise RuntimeError(
            "STOP: evaluation time not reached"
        )

    if (now.date() - base_date).days > 7:
        raise RuntimeError(
            "STOP: BASE_DATE too old"
        )

    return base_date, cutoff


def comparison_cutoffs(evaluation_cutoff):
    price_cutoff = datetime.combine(
        evaluation_cutoff.date(),
        PRICE_CUTOFF_TIME,
        tzinfo=JST,
    )

    cme_calendar = xcals.get_calendar("CMES")
    dates = []

    for offset in range(10):
        candidate = (
            price_cutoff.date()
            - timedelta(days=offset)
        )

        if cme_calendar.is_session(
            pd.Timestamp(candidate)
        ):
            dates.append(candidate)

        if len(dates) == 2:
            break

    if len(dates) != 2:
        raise RuntimeError(
            "STOP: CME comparison dates unavailable"
        )

    return (
        datetime.combine(
            dates[0], PRICE_CUTOFF_TIME, tzinfo=JST
        ),
        datetime.combine(
            dates[1], PRICE_CUTOFF_TIME, tzinfo=JST
        ),
    )


def save_json(path, payload):
    path.parent.mkdir(
        parents=True, exist_ok=True
    )

    temporary = path.with_name(
        path.name + ".tmp"
    )

    try:
        temporary.write_text(
            json.dumps(
                payload,
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


def main():
    base_date, cutoff = get_dates()

    current_cutoff, previous_cutoff = (
        comparison_cutoffs(cutoff)
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
        now=cutoff,
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "STOP: CME data freshness failed"
        )

    value = validated.get("value")
    previous = validated.get("previous_close")
    change = validated.get("change_pct")

    for name, number in (
        ("value", value),
        ("previous_close", previous),
        ("change_pct", change),
    ):
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise RuntimeError(
                f"STOP: invalid CME {name}"
            )

    if value <= 0 or previous <= 0:
        raise RuntimeError(
            "STOP: invalid CME prices"
        )

    calculated = (value / previous - 1) * 100

    if abs(calculated - change) > 0.01:
        raise RuntimeError(
            "STOP: CME percentage inconsistent"
        )

    if abs(change) >= 5:
        raise RuntimeError(
            "STOP: CME large change requires review"
        )

    validated.update({
        "key": "nikkei225_futures_cme",
        "name": "日経225先物（CME）",
        "category": "futures",
        "evaluation_base_date": base_date.isoformat(),
        "evaluation_cutoff_jst": cutoff.isoformat(),
        "contract_month_verified": False,
        "contract_month_note": NOTE,
        "manual_review_required": False,
        "status": "ok",
        "usable": True,
    })

    payload = {
        "base_date": base_date.isoformat(),
        "generated_at": datetime.now(
            JST
        ).isoformat(),
        "evaluation_status": "ok",
        "official_publication_allowed": True,
        "results": [validated],
        "quality_notes": [NOTE],
    }

    save_json(OFFICIAL_OUTPUT, payload)

    print(
        "[CME MARKET DATA READY]",
        f"base_date={base_date}",
        f"change_pct={change:.4f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
