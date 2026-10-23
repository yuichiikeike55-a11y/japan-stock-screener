
"""
市場データ鮮度判定の単体テスト。

固定時刻を使い、
stale / ok / stale の3ケースを確認する。

注意:
closed は休場カレンダーに基づく判定であり、
単純な経過時間判定では使用しない。
"""

from datetime import datetime, timezone

from market_data.validators import validate_freshness


def make_data(as_of):
    return {
        "symbol": "NIY=F",
        "source": "yfinance",
        "value": 65830.0,
        "previous_close": 64560.0,
        "change": 1270.0,
        "change_pct": 1.9671623296158611,
        "as_of": as_of,
    }


def check_case(name, data, now, expected):
    result = validate_freshness(
        data,
        max_age_minutes=180,
        now=now,
    )

    actual = result.get("status")

    print(f"{name}: {actual} (expected: {expected})")

    if actual != expected:
        raise RuntimeError(
            f"{name} failed: "
            f"expected={expected}, actual={actual}"
        )


def main():
    print("=== Freshness Validator Test ===")

    # CASE 1
    # 日曜日 + 44時間前の金曜日データ
    # 鮮度180分超過 → stale
    check_case(
        "CASE 1",
        make_data("2026-09-04T16:00:00+00:00"),
        datetime(
            2026, 9, 6, 12, 0,
            tzinfo=timezone.utc,
        ),
        "stale",
    )

    # CASE 2
    # 60分前 → ok
    check_case(
        "CASE 2",
        make_data("2026-09-04T16:00:00+00:00"),
        datetime(
            2026, 9, 4, 17, 0,
            tzinfo=timezone.utc,
        ),
        "ok",
    )

    # CASE 3
    # 240分前 → stale
    check_case(
        "CASE 3",
        make_data("2026-09-04T16:00:00+00:00"),
        datetime(
            2026, 9, 4, 20, 0,
            tzinfo=timezone.utc,
        ),
        "stale",
    )

    print("=== FRESHNESS CHECK PASSED ===")


if __name__ == "__main__":
    main()
