
"""
市場データ取得ランナー。

- CME先物: 確定済み1時間足と日足を取得
- 取得失敗時は再試行
- 大阪先物: 検証済みJSONがある場合のみ利用
- 取得失敗を明示したJSONを出力
- 基準日の異なるデータは正式評価に使用しない
"""

import json
import math
import os
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
    fetch_verified_osaka_futures,
)
from market_data.normalizers import (
    normalize_yfinance,
    normalize_verified_osaka,
)
from market_data.validators import validate_freshness
from market_data.cme_calendar import get_verified_session_end

JST = ZoneInfo("Asia/Tokyo")

OUTPUT = Path("output/market_data.json")
HISTORY_DIR = Path("output/market_data_history")

CME_SYMBOL = "NKD=F"
MAX_AGE_MINUTES = 180
RETRY_COUNT = 3
RETRY_SECONDS = 15


def get_base_date():
    raw = os.getenv("BASE_DATE", "").strip()

    if raw:
        return date.fromisoformat(raw)

    now = datetime.now(JST)
    candidate = now.date()

    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)

    return candidate



def get_cutoff(base_date):
    now = datetime.now(JST)

    # 金曜日なら月曜日、それ以外は翌日
    days_ahead = 3 if base_date.weekday() == 4 else 1
    next_day = base_date + timedelta(days=days_ahead)

    cutoff = datetime.combine(
        next_day,
        dt_time(7, 0),
        tzinfo=JST,
    )

    return min(now, cutoff)
def get_cme_regular_session_end(base_date):
    """
    CME日経225先物の通常取引終了時刻を計算する。

    米国東部時間17:00を日本時間に変換する。
    夏時間・冬時間の切り替えはZoneInfoで処理する。

    注意:
    休場日・短縮取引日は、この関数だけでは検証できない。
    この時刻だけを根拠にCMEデータを有効化しない。
    """
    eastern = ZoneInfo("America/New_York")

    session_end_eastern = datetime.combine(
        base_date,
        dt_time(17, 0),
        tzinfo=eastern,
    )

    return session_end_eastern.astimezone(JST)
def finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def unavailable_result(key, name, reason):
    return {
        "key": key,
        "name": name,
        "status": "unavailable",
        "usable": False,
        "reason": str(reason),
        "change_pct": None,
    }


def fetch_cme(base_date, cutoff):
    last_error = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            hourly = fetch_yfinance(CME_SYMBOL)
            daily = fetch_yfinance_daily(CME_SYMBOL)
            # --------------------------------------------
            # CME日足の基準日検証
            # 日付が異なる場合は正式評価を停止
            # --------------------------------------------
            if daily is None or daily.empty:
                raise RuntimeError(
                    "CME daily data missing"
                )

            latest_daily_date = daily.index[-1].date()

            if latest_daily_date != base_date:
                raise RuntimeError(
                    "CME daily base date mismatch: "
                    f"expected={base_date.isoformat()}, "
                    f"actual={latest_daily_date.isoformat()}"
                )
            normalized = normalize_yfinance(
                CME_SYMBOL,
                hourly,
                daily,
                cutoff=cutoff,
            )
            # --------------------------------------------
            # CME通常取引終了時刻との照合（診断のみ）
            # --------------------------------------------
            expected_end = get_verified_session_end(
                base_date
            )

            actual_end = datetime.fromisoformat(
                normalized["as_of"]
            ).astimezone(JST)

            session_end_match = (
                actual_end == expected_end
            )
            # --------------------------------------------
            # CME終了時刻の不一致は正式評価を停止
            # --------------------------------------------
            if not session_end_match:
                raise RuntimeError(
                    "CME session end mismatch: "
                    f"expected={expected_end.isoformat()}, "
                    f"actual={actual_end.isoformat()}"
                )
            print(
                "[CME SESSION CHECK]",
                f"base_date={base_date.isoformat()}",
                f"expected_end_jst={expected_end.isoformat()}",
                f"actual_end_jst={actual_end.isoformat()}",
                f"session_end_match={session_end_match}",
                flush=True,
            )
            validated = validate_freshness(
                normalized,
                MAX_AGE_MINUTES,
                now=cutoff,
            )

            change = validated.get("change_pct")

            if not finite_number(change):
                raise RuntimeError(
                    "CME change_pct is invalid"
                )

            status = validated.get("status")
            usable = status == "ok"

            return {
                "key": "nikkei225_futures_cme",
                "name": "日経225先物（CME）",
                "category": "futures",
                **validated,
                "usable": usable,
                "evaluation_base_date": base_date.isoformat(),
                "evaluation_cutoff_jst": cutoff.isoformat(),
                "as_of_jst": validated.get("as_of"),
                "attempts": attempt,
            }

        except Exception as exc:
            last_error = str(exc)
            print(
                f"CME attempt {attempt}/{RETRY_COUNT} "
                f"failed: {last_error}",
                flush=True,
            )

            if attempt < RETRY_COUNT:
                time.sleep(RETRY_SECONDS)

    result = unavailable_result(
        "nikkei225_futures_cme",
        "日経225先物（CME）",
        last_error or "unknown_error",
    )
    result["category"] = "futures"
    result["evaluation_base_date"] = base_date.isoformat()
    result["evaluation_cutoff_jst"] = cutoff.isoformat()
    result["attempts"] = RETRY_COUNT
    return result


def fetch_osaka(base_date, cutoff):
    try:
        raw = fetch_verified_osaka_futures(base_date)
        normalized = normalize_verified_osaka(raw)

        quote_time = datetime.fromisoformat(
            normalized["as_of"]
        ).astimezone(JST)


        if quote_time > cutoff:
            raise RuntimeError(
                "Osaka quote is after evaluation cutoff"
            )

        # 評価期限から3時間以内の価格のみ採用
        age_minutes = (
            cutoff - quote_time
        ).total_seconds() / 60

        if age_minutes > MAX_AGE_MINUTES:
            raise RuntimeError(
                "Osaka quote is stale: "
                f"{age_minutes:.0f} minutes old"
            )

        if normalized.get("trading_date") != base_date.isoformat():
            raise RuntimeError(
                "Osaka trading date mismatch"
            )

        change = normalized.get("change_pct")

        if not finite_number(change):
            raise RuntimeError(
                "Osaka change_pct is invalid"
            )

        return {
            "key": "nikkei225_futures_osaka",
            "name": "日経225先物（大阪）",
            "category": "futures",
            **normalized,
            "status": "ok",
            "usable": True,
            "evaluation_base_date": base_date.isoformat(),
            "evaluation_cutoff_jst": cutoff.isoformat(),
        }

    except Exception as exc:
        result = unavailable_result(
            "nikkei225_futures_osaka",
            "日経225先物（大阪）",
            exc,
        )
        result["category"] = "futures"
        result["evaluation_base_date"] = base_date.isoformat()
        result["evaluation_cutoff_jst"] = cutoff.isoformat()
        return result


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_name(path.name + ".tmp")

    try:
        temporary.write_text(
            json.dumps(
                data,
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
    base_date = get_base_date()
    now = datetime.now(JST)

    if base_date > now.date():
        raise RuntimeError(
            "BASE_DATE cannot be in the future"
        )

    if base_date.weekday() >= 5:
        raise RuntimeError(
            "BASE_DATE must be a weekday"
        )

    if (now.date() - base_date).days > 7:
        raise RuntimeError(
            "BASE_DATE is older than 7 days"
        )

    cutoff = get_cutoff(base_date)

    print("BASE_DATE:", base_date.isoformat())
    print("CUTOFF:", cutoff.isoformat())


    # --------------------------------------------------------
    # CME日経225先物のみ取得
    # 大阪先物は正式評価から廃止
    # --------------------------------------------------------

    cme = fetch_cme(base_date, cutoff)

    results = [cme]

    # CMEが正常な場合のみ市場データを有効にする
    status = (
        "ok"
        if (
            cme.get("status") == "ok"
            and cme.get("usable") is True
            and cme.get("evaluation_base_date")
                == base_date.isoformat()
        )
        else "unavailable"
    )

    payload = {
        "base_date": base_date.isoformat(),
        "generated_at_jst": datetime.now(JST).isoformat(),
        "evaluation_status": status,
        "results": results,
    }

    history_path = (
        HISTORY_DIR
        / f"market_data_{base_date.isoformat()}.json"
    )

    # 履歴は基準日ごとに保存。
    # 最新ファイルと履歴ファイルを同じ内容にする。
    write_json_atomic(history_path, payload)
    write_json_atomic(OUTPUT, payload)

    print("MARKET DATA STATUS:", status)

    for result in results:
        print(
            result["key"],
            result["status"],
            result.get("reason", ""),
        )


if __name__ == "__main__":
    main()
