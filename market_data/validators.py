
"""
市場データの鮮度検証。
CME先物の確定済み1時間足を評価する。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")


def get_latest_trading_date(now):
    if now.weekday() >= 5:
        return now.date() - timedelta(
            days=now.weekday() - 4
        )
    return now.date()


def validate_freshness(
    data,
    max_age_minutes,
    now=None,
):
    if not data.get("as_of"):
        raise RuntimeError("as_of is missing")

    try:
        as_of = datetime.fromisoformat(
            data["as_of"]
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Invalid as_of timestamp"
        ) from exc

    if as_of.tzinfo is None:
        raise RuntimeError(
            "as_of must include timezone"
        )

    if now is None:
        now = datetime.now(JST)

    if now.tzinfo is None:
        raise RuntimeError(
            "now must include timezone"
        )

    as_of = as_of.astimezone(JST)
    now = now.astimezone(JST)

    if as_of > now:
        raise RuntimeError(
            "as_of is after evaluation time"
        )

    age_minutes = (
        now - as_of
    ).total_seconds() / 60

    result = dict(data)
    result["age_minutes"] = round(
        age_minutes, 1
    )

    if age_minutes <= max_age_minutes:
        result["status"] = "ok"
        result["reason"] = "within_age_limit"
    else:
        result["status"] = "stale"
        result["reason"] = "age_exceeds_max_age"

    return result
