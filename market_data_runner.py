
"""
無料運用版：CME先物のみ取得。

通常時は180分以内の鮮度を要求。
土日は直近の金曜CME取引終了後のデータに限り、
週末の休場を考慮する。

過去・未来のBASE_DATEは検証済み保存データがない限り停止。
取得失敗・日付不整合・不正データでは保存しない。
"""

import json
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

NORMAL_MAX_AGE_MINUTES = 180
WEEKEND_MAX_AGE_MINUTES = 60 * 72


def parse_datetime(value):
    if not value:
        raise RuntimeError("CME observation time is missing")

    result = datetime.fromisoformat(str(value))

    if result.tzinfo is None:
        raise RuntimeError(
            "CME observation has no timezone"
        )

    return result.astimezone(JST)


def weekend_freshness_allowed(
    now_jst,
    observation_jst,
):
    """
    土日のみ適用する限定的な例外。

    直近の金曜05:00 JST以降の観測値で、
    72時間以内の場合だけ候補とする。

    これは祝日・臨時休場の完全な判定ではない。
    """
    if now_jst.weekday() not in (5, 6):
        return False

    days_since_friday = (
        now_jst.weekday() - 4
    )

    friday = (
        now_jst.date()
        - timedelta(days=days_since_friday)
    )

    earliest = datetime.combine(
        friday,
        time(5, 0),
        tzinfo=JST,
    )

    age_minutes = (
        now_jst - observation_jst
    ).total_seconds() / 60

    return (
        earliest <= observation_jst <= now_jst
        and 0 <= age_minutes
        <= WEEKEND_MAX_AGE_MINUTES
    )


def main():
    now_jst = datetime.now(JST)

    base_date_text = os.getenv(
        "BASE_DATE", ""
    ).strip()

    base_date = (
        datetime.strptime(
            base_date_text,
            "%Y-%m-%d",
        ).date()
        if base_date_text
        else now_jst.date()
    )

    if base_date != now_jst.date():
        raise RuntimeError(
            "Historical/future BASE_DATE "
            "is not supported without a "
            "verified saved snapshot. "
            f"BASE_DATE={base_date} "
            f"today={now_jst.date()}"
        )

    evaluation_cutoff = datetime.combine(
        base_date,
        time(20, 30),
        tzinfo=JST,
    )

    effective_cutoff = min(
        now_jst,
        evaluation_cutoff,
    )

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
        NORMAL_MAX_AGE_MINUTES,
        now=effective_cutoff,
    )

    print(
        "CME freshness:",
        validated.get("status"),
        validated.get("as_of"),
        validated.get("age_minutes"),
    )

    if validated.get("status") != "ok":
        reason = validated.get("reason")

        if reason != "age_exceeds_max_age":
            raise RuntimeError(
                "CME futures unavailable: "
                f"{reason}"
            )

        observation_jst = parse_datetime(
            validated.get("as_of")
        )

        if not weekend_freshness_allowed(
            effective_cutoff,
            observation_jst,
        ):
            raise RuntimeError(
                "CME futures stale and "
                "weekend exception not applicable"
            )

        print(
            "Weekend CME freshness exception "
            "accepted:",
            observation_jst.isoformat(),
        )

        validated = dict(validated)
        validated["status"] = "ok"
        validated["reason"] = (
            "weekend_market_closed"
        )
        validated["freshness_exception"] = True

    as_of_jst = parse_datetime(
        validated.get("as_of")
    )

    if as_of_jst > effective_cutoff:
        raise RuntimeError(
            "CME observation after cutoff"
        )

    if validated.get("change_pct") is None:
        raise RuntimeError(
            "CME change_pct is missing"
        )

    result = {
        "key": CME_KEY,
        "name": "日経225先物（CME）",
        "category": "futures",
        **validated,
        "as_of_jst": as_of_jst.isoformat(),
        "evaluation_base_date": (
            base_date.isoformat()
        ),
        "evaluation_cutoff_jst": (
            evaluation_cutoff.isoformat()
        ),
    }

    output_data = {
        "results": [result]
    }

    snapshot_file = (
        HISTORY_DIR
        / f"market_data_{base_date.isoformat()}.json"
    )

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
            previous_time = parse_datetime(
                previous.get("as_of")
            )

            if as_of_jst < previous_time:
                raise RuntimeError(
                    "Existing CME snapshot is newer. "
                    "Refusing overwrite."
                )

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
