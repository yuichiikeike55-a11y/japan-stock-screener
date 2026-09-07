"""
市場データの検証処理。

標準化された市場データについて、
データ鮮度などを判定する。

この段階では、
平日と土日の判定に対応する。

祝日・取引所固有の休場日は
後続段階で追加する。
"""

from datetime import datetime
from datetime import timedelta

def get_latest_trading_date(now):
    """
    現時点で期待される最新取引日を返す。

    現段階では土日のみ対応。
    土曜・日曜は直近金曜日、
    平日は当日を返す。
    """
    if now.weekday() >= 5:
        days_since_friday = now.weekday() - 4
        return now.date() - timedelta(days=days_since_friday)

    return now.date()

def validate_freshness(
    data,
    max_age_minutes,
    now=None,
):
    """
    市場データの鮮度を判定する。

    平日:
        最新データが当日で、
        max_age_minutes以内なら ok。

    土日:
        直近金曜日のデータであれば
        closed とする。

    stale:
        更新が期待される状況で
        データが古い場合。
    """

    if "as_of" not in data:
        raise RuntimeError(
            "as_of is missing"
        )

    as_of_text = data["as_of"]

    try:
        as_of = datetime.fromisoformat(
            as_of_text
        )

    except (TypeError, ValueError) as e:
        raise RuntimeError(
            f"invalid as_of: {as_of_text}"
        ) from e

    if as_of.tzinfo is None:
        raise RuntimeError(
            "as_of must include timezone"
        )

    # =====================================
    # 現在時刻
    # =====================================

    if now is None:
        now = datetime.now(
            tz=as_of.tzinfo
        )

    elif now.tzinfo is None:
        raise RuntimeError(
            "now must include timezone"
        )

    else:
        now = now.astimezone(
            as_of.tzinfo
        )

    if as_of > now:
        raise RuntimeError(
            "as_of is in the future"
        )

    # =====================================
    # 土日
    # =====================================

    # Monday = 0
    # Saturday = 5
    # Sunday = 6

    if now.weekday() >= 5:
        days_since_friday = (
            now.weekday()
            - 4
        )

        latest_expected_date = (
            now.date()
            - timedelta(
                days=days_since_friday
            )
        )

        if (
            as_of.date()
            == latest_expected_date
        ):
            result = dict(data)

            result["status"] = (
                "closed"
            )

            return result

        result = dict(data)

        result["status"] = (
            "stale"
        )

        return result

    # =====================================
    # 平日
    # =====================================

    if (
        as_of.date()
        != now.date()
    ):
        result = dict(data)

        result["status"] = (
            "stale"
        )

        return result

    age = (
        now
        - as_of
    )

    age_minutes = (
        age.total_seconds()
        / 60
    )

    result = dict(data)

    if (
        age_minutes
        <= max_age_minutes
    ):
        result["status"] = (
            "ok"
        )

    else:
        result["status"] = (
            "stale"
        )

    return result