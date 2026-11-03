
"""
CME NKD=F 1時間足・日足対応診断。

読み取り専用。
本番JSON・採点結果を変更しない。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)

JST = ZoneInfo("Asia/Tokyo")
ET = ZoneInfo("America/New_York")
SYMBOL = "NKD=F"


def main():
    now = datetime.now(JST)

    print("[CME REFERENCE DIAGNOSTIC START]", flush=True)
    print("NOW_JST:", now.isoformat(), flush=True)
    print(
        "NOW_EASTERN:",
        now.astimezone(ET).isoformat(),
        flush=True,
    )

    hourly = fetch_yfinance(SYMBOL)
    daily = fetch_yfinance_daily(SYMBOL)

    if hourly is None or hourly.empty:
        raise RuntimeError("CME hourly data missing")

    if daily is None or daily.empty:
        raise RuntimeError("CME daily data missing")

    if "Close" not in hourly.columns:
        raise RuntimeError("CME hourly Close missing")

    if "Close" not in daily.columns:
        raise RuntimeError("CME daily Close missing")

    if hourly.index.tz is None:
        raise RuntimeError("CME hourly timezone missing")

    hourly = hourly.sort_index().copy()
    hourly.index = hourly.index.tz_convert(JST)

    daily = daily.sort_index().copy()

    # Yahooの時刻ラベルが足の開始時刻であると仮定
    hourly["calculated_end"] = (
        hourly.index + pd.Timedelta(hours=1)
    )

    completed = hourly.loc[
        hourly["calculated_end"] <= now
    ].copy()

    if completed.empty:
        raise RuntimeError("No completed hourly bars")

    print("\n[LAST 15 COMPLETED HOURLY BARS]")

    for start, row in completed.tail(15).iterrows():
        end = row["calculated_end"]
        print(
            f"start_jst={start.isoformat()}",
            f"end_jst={end.isoformat()}",
            f"start_et={start.tz_convert(ET).isoformat()}",
            f"end_et={end.tz_convert(ET).isoformat()}",
            f"close={row['Close']}",
            flush=True,
        )

    print("\n[LAST 10 DAILY BARS]")

    for stamp, row in daily.tail(10).iterrows():
        print(
            f"daily_label={stamp}",
            f"close={row['Close']}",
            flush=True,
        )

    latest_start = completed.index[-1]
    latest_end = completed.iloc[-1]["calculated_end"]
    latest_close = float(completed.iloc[-1]["Close"])

    print("\n[LATEST COMPLETED BAR]")
    print("start_jst:", latest_start.isoformat())
    print("end_jst:", latest_end.isoformat())
    print("close:", latest_close)
    print(
        "age_minutes:",
        round((now - latest_end).total_seconds() / 60, 1),
    )

    print("\n[DAILY REFERENCE CANDIDATES]")

    # 診断目的で直近3本の日足を比較。
    # 正式な前日終値としては未承認。
    for stamp, row in daily.tail(3).iterrows():
        candidate = float(row["Close"])

        if candidate <= 0:
            continue

        change_pct = (
            (latest_close - candidate)
            / candidate
            * 100
        )

        print(
            f"daily_label={stamp}",
            f"candidate_close={candidate}",
            f"hypothetical_change_pct={change_pct:.4f}",
            "verified_reference=False",
            flush=True,
        )

    print("\n[REFERENCE STATUS]")
    print("verified_reference=False")
    print("official_scoring_allowed=False")
    print("[CME REFERENCE DIAGNOSTIC COMPLETE]")


if __name__ == "__main__":
    main()
