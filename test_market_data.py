"""
市場データ鮮度判定の単体テスト。

固定時刻を使い、
closed / ok / stale の
3ケースを確認する。
"""

from datetime import datetime
from datetime import timezone

from market_data.validators import (
    validate_freshness,
)


def make_data(as_of):
    """
    テスト用の標準化済みデータを作る。
    """

    return {
        "symbol": "NIY=F",
        "source": "yfinance",
        "value": 65830.0,
        "previous_close": 64560.0,
        "change": 1270.0,
        "change_pct": 1.9671623296158611,
        "as_of": as_of,
    }


def main():
    print(
        "=== Freshness Validator Test ==="
    )

    max_age_minutes = 180

    # =====================================
    # CASE 1
    # 日曜日 + 直近金曜日データ
    # → closed
    # =====================================

    sunday_now = datetime(
        2026,
        9,
        6,
        12,
        0,
        tzinfo=timezone.utc,
    )

    friday_data = make_data(
        "2026-09-04T16:00:00+00:00"
    )

    result = validate_freshness(
        friday_data,
        max_age_minutes,
        now=sunday_now,
    )

    print()
    print("CASE 1")
    print(
        "status:",
        result["status"],
    )

    if result["status"] != "closed":
        raise RuntimeError(
            "CASE 1 failed"
        )

    # =====================================
    # CASE 2
    # 平日 + 60分前
    # → ok
    # =====================================

    weekday_now = datetime(
        2026,
        9,
        4,
        17,
        0,
        tzinfo=timezone.utc,
    )

    fresh_data = make_data(
        "2026-09-04T16:00:00+00:00"
    )

    result = validate_freshness(
        fresh_data,
        max_age_minutes,
        now=weekday_now,
    )

    print()
    print("CASE 2")
    print(
        "status:",
        result["status"],
    )

    if result["status"] != "ok":
        raise RuntimeError(
            "CASE 2 failed"
        )

    # =====================================
    # CASE 3
    # 平日 + 4時間前
    # → stale
    # =====================================

    stale_now = datetime(
        2026,
        9,
        4,
        20,
        0,
        tzinfo=timezone.utc,
    )

    stale_data = make_data(
        "2026-09-04T16:00:00+00:00"
    )

    result = validate_freshness(
        stale_data,
        max_age_minutes,
        now=stale_now,
    )

    print()
    print("CASE 3")
    print(
        "status:",
        result["status"],
    )

    if result["status"] != "stale":
        raise RuntimeError(
            "CASE 3 failed"
        )

    print()
    print(
        "=== FRESHNESS CHECK PASSED ==="
    )


if __name__ == "__main__":
    main()