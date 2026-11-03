
"""
CME NKD=F diagnostic only.

Does not modify official market JSON.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)

JST = ZoneInfo("Asia/Tokyo")
EASTERN = ZoneInfo("America/New_York")


def main():
    now = datetime.now(JST)

    print("[DIAGNOSTIC START]", flush=True)
    print("NOW_JST:", now.isoformat())
    print(
        "NOW_EASTERN:",
        now.astimezone(EASTERN).isoformat(),
    )

    hourly = fetch_yfinance("NKD=F")
    daily = fetch_yfinance_daily("NKD=F")

    if hourly.index.tz is None:
        raise RuntimeError(
            "Hourly timezone missing"
        )

    hourly = hourly.copy().sort_index()
    hourly.index = hourly.index.tz_convert(JST)

    print(
        "[HOURLY TIMEZONE]",
        str(hourly.index.tz),
    )

    print("[LAST 12 HOURLY BARS]")

    for timestamp, row in hourly.tail(12).iterrows():
        completed = timestamp + timedelta(hours=1)
        age = (now - completed).total_seconds() / 60

        print(
            "start=", timestamp.isoformat(),
            "end=", completed.isoformat(),
            "close=", row.get("Close"),
            "age_minutes=", round(age, 1),
            "completed_by_clock=", completed <= now,
        )

    print("[LAST 10 DAILY BARS]")

    for timestamp, row in daily.tail(10).iterrows():
        print(
            "date=", timestamp.isoformat(),
            "close=", row.get("Close"),
        )

    print("[DIAGNOSTIC COMPLETE]", flush=True)


if __name__ == "__main__":
    main()
