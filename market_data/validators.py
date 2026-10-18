
"""
市場データの鮮度検証。

不明な取引時間を推測してclosed扱いにしない。
"""

from datetime import datetime, timedelta


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

    as_of = datetime.fromisoformat(data["as_of"])

    if as_of.tzinfo is None:
        raise RuntimeError(
            "as_of must include timezone"
        )

    if now is None:
        now = datetime.now(as_of.tzinfo)

    if now.tzinfo is None:
        raise RuntimeError(
            "now must include timezone"
        )

    now = now.astimezone(as_of.tzinfo)

    if as_of > now:
        raise RuntimeError(
            "as_of is after evaluation time"
        )

    age_minutes = (
        now - as_of
    ).total_seconds() / 60

    result = dict(data)
    result["age_minutes"] = round(age_minutes, 1)

    if age_minutes <= max_age_minutes:
        result["status"] = "ok"
        result["reason"] = "within_age_limit"
    else:
        result["status"] = "stale"
        result["reason"] = "age_exceeds_max_age"

    return result
