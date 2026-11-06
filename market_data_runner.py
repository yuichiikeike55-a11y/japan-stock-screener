
"""
翌東証営業日の寄り付き前に評価する市場データランナー。

正式評価条件:
- 東証の直近取引終了済み営業日を基準日とする
- 翌東証営業日の08:45 JSTを評価時刻とする
- CMEの確定済み1時間足のみ利用
- CMEセッション・日足の対応が未検証なら停止
- 正常データのみ最新JSONへ公開
"""

import json
import math
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)
from market_data.normalizers import normalize_yfinance
from market_data.validators import validate_freshness
from market_data.cme_calendar import get_verified_session_end

JST = ZoneInfo("Asia/Tokyo")
EASTERN = ZoneInfo("America/New_York")

OUTPUT = Path("output/market_data.json")
HISTORY_DIR = Path("output/market_data_history")

CME_SYMBOL = "NKD=F"
MAX_AGE_MINUTES = 180
EVALUATION_TIME = time(8, 45)


def get_tse_calendar():
    return xcals.get_calendar("XTKS")


def is_tse_session(day):
    calendar = get_tse_calendar()
    return bool(
        calendar.is_session(
            pd.Timestamp(day.isoformat())
        )
    )


def previous_tse_session(day):
    calendar = get_tse_calendar()
    stamp = pd.Timestamp(day.isoformat())

    if calendar.is_session(stamp):
        stamp = calendar.previous_session(stamp)
    else:
        stamp = calendar.date_to_session(
            stamp,
            direction="previous",
        )

    return stamp.date()


def next_tse_session(day):
    calendar = get_tse_calendar()
    stamp = pd.Timestamp(day.isoformat())

    return calendar.next_session(stamp).date()



def get_base_date_and_cutoff():
    """
    翌東証営業日の寄り付き前評価。

    - 評価時刻は東証営業日の08:45 JST
    - 基準日は評価日の前東証営業日
    - 08:45前は正式評価を停止
    - BASE_DATE指定時も営業日を厳密検証
    """
    now = datetime.now(JST)
    calendar = get_tse_calendar()

    raw = os.getenv("BASE_DATE", "").strip()

    if raw:
        base_date = date.fromisoformat(raw)

        if not is_tse_session(base_date):
            raise RuntimeError(
                f"BASE_DATE is not a TSE session: {base_date}"
            )

        evaluation_date = next_tse_session(base_date)
    else:
        today = now.date()
        today_stamp = pd.Timestamp(today.isoformat())

        if calendar.is_session(today_stamp):
            evaluation_date = today
        else:
            evaluation_date = calendar.date_to_session(
                today_stamp,
                direction="next",
            ).date()

        base_date = previous_tse_session(
            evaluation_date
        )

    cutoff = datetime.combine(
        evaluation_date,
        EVALUATION_TIME,
        tzinfo=JST,
    )

    if now < cutoff:
        raise RuntimeError(
            "Pre-open evaluation time has not arrived: "
            f"now={now.isoformat()}, "
            f"cutoff={cutoff.isoformat()}"
        )

    if (now.date() - base_date).days > 7:
        raise RuntimeError(
            "BASE_DATE is older than 7 days"
        )

    print(
        "TSE EVALUATION DATE:",
        evaluation_date.isoformat(),
    )

    return base_date, cutoff


def get_cme_session_date(cutoff):
    """
    評価時刻までに終了した直近のCMEセッションを探す。

    - CMEカレンダーで非営業日と確認できた日だけ飛ばす
    - カレンダー検証の異常は握りつぶさず停止
    - 直近セッションが未終了なら正式評価を停止
    """
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("CMES")
    candidate = cutoff.astimezone(EASTERN).date()

    for days_back in range(8):
        session_date = candidate - timedelta(
            days=days_back
        )

        stamp = pd.Timestamp(
            session_date.isoformat()
        )

        if not calendar.is_session(stamp):
            continue


        print(
            "[CME SESSION CANDIDATE]",
            f"date={session_date.isoformat()}",
            f"cutoff={cutoff.isoformat()}",
            flush=True,
        )

        session_end = get_verified_session_end(
            session_date
        )

        if session_end > cutoff:
            raise RuntimeError(
                "Latest CME session has not ended: "
                f"session={session_date}, "
                f"end={session_end.isoformat()}, "
                f"cutoff={cutoff.isoformat()}"
            )

        print(
            "CME SESSION DATE:",
            session_date.isoformat(),
        )
        print(
            "CME SESSION END:",
            session_end.isoformat(),
        )

        return session_date, session_end

    raise RuntimeError(
        "No verified CME session within 8 days"
    )


def build_market_data(base_date, cutoff):
    cme_date, cme_end = get_cme_session_date(
        cutoff
    )

    hourly = fetch_yfinance(CME_SYMBOL)
    daily = fetch_yfinance_daily(CME_SYMBOL)

    print(
        "[CME DATA FETCH]",
        f"hourly_rows={0 if hourly is None else len(hourly)}",
        f"daily_rows={0 if daily is None else len(daily)}",
        flush=True,
    )

    if hourly is not None and not hourly.empty:
        print(
            "[CME HOURLY RANGE]",
            f"first={hourly.index[0]}",
            f"last={hourly.index[-1]}",
            flush=True,
        )

    if daily is not None and not daily.empty:
        print(
            "[CME DAILY RANGE]",
            f"first={daily.index[0]}",
            f"last={daily.index[-1]}",
            flush=True,
        )
    if daily is None or daily.empty:
        raise RuntimeError("CME daily data missing")

    # 日足の最終行ではなく、評価対象セッションを明示的に確認する。
    # 日足インデックスはプロバイダー由来のラベルであり、
    # それだけでは確定済みセッションとは断定しない。
    # CME日足の直近5行を診断
    print(
        "[CME DAILY ROWS]",
        [
            {
                "date": str(index),
                "close": float(row["Close"]),
            }
            for index, row in daily.tail(5).iterrows()
        ],
        flush=True,
    )

    # CME時間足の終了時刻と終値を診断
    if hourly is None or hourly.empty:
        raise RuntimeError("CME hourly data missing")

    if hourly.index.tz is None:
        raise RuntimeError("CME hourly timezone missing")

    hourly_jst = hourly.copy()
    hourly_jst.index = hourly_jst.index.tz_convert(JST)

    completed_hourly = hourly_jst.loc[
        hourly_jst.index + pd.Timedelta(hours=1)
        <= cme_end
    ]

    if completed_hourly.empty:
        raise RuntimeError(
            "CME completed hourly data missing"
        )

    print(
        "[CME HOURLY CLOSE CHECK]",
        f"last_start={completed_hourly.index[-1]}",
        f"last_close={completed_hourly.iloc[-1]['Close']}",
        f"session_end={cme_end.isoformat()}",
        flush=True,
    )
    # CMEセッション終了前後の時間足を診断
    hourly_debug = hourly.copy()

    if hourly_debug.index.tz is None:
        raise RuntimeError(
            "CME hourly timezone missing"
        )

    hourly_debug.index = hourly_debug.index.tz_convert(JST)

    print(
        "[CME HOURLY SESSION DETAIL]",
        [
            {
                "start_jst": index.isoformat(),
                "close": float(row["Close"]),
                "volume": (
                    float(row["Volume"])
                    if "Volume" in hourly_debug.columns
                    and pd.notna(row["Volume"])
                    else None
                ),
            }
            for index, row in hourly_debug.iterrows()
            if (
                cme_end - timedelta(hours=8)
                <= index
                <= cme_end + timedelta(hours=2)
            )
        ],
        flush=True,
    )    
    daily_dates = [
        stamp.date()
        for stamp in daily.index
    ]

    matching_positions = [
        i
        for i, session_day in enumerate(daily_dates)
        if session_day == cme_date
    ]

    if len(matching_positions) != 1:
        raise RuntimeError(
            "CME target daily row missing or duplicated: "
            f"expected={cme_date}, "
            f"matches={len(matching_positions)}, "
            f"available={daily_dates}"
        )

    target_position = matching_positions[0]

    if target_position != len(daily) - 1:
        print(
            "[CME DAILY TARGET FOUND]",
            f"target={cme_date}",
            f"position={target_position}",
            f"latest={daily_dates[-1]}",
            flush=True,
        )

    # ここでは対象行の存在だけを確認する。
    # 確定済みかどうかは時間足との照合が必要。
    # 未検証の日足を正式評価へ渡さない。
    if target_position != len(daily) - 1:
        raise RuntimeError(
            "CME target daily row requires independent "
            "session-close verification: "
            f"target={cme_date}, "
            f"latest={daily_dates[-1]}"
        )

    normalized = normalize_yfinance(
        CME_SYMBOL,
        hourly,
        daily,
        cutoff=cme_end,
        session_date=cme_date,
    )

    validated = validate_freshness(
        normalized,
        MAX_AGE_MINUTES,
        now=cutoff,
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "CME freshness validation failed: "
            f"{validated.get('reason')}"
        )

    as_of = datetime.fromisoformat(
        validated["as_of"]
    ).astimezone(JST)

    if as_of > cme_end:
        raise RuntimeError(
            "CME quote after session end"
        )

    change = validated.get("change_pct")

    if (
        not isinstance(change, (int, float))
        or isinstance(change, bool)
        or not math.isfinite(change)
    ):
        raise RuntimeError(
            "CME change_pct invalid"
        )

    result = {
        **validated,
        "key": "nikkei225_futures_cme",
        "name": "日経225先物（CME）",
        "category": "futures",
        "usable": True,
        "evaluation_base_date": base_date.isoformat(),
        "evaluation_cutoff_jst": cutoff.isoformat(),
        "cme_session_date": cme_date.isoformat(),
        "cme_session_end_jst": cme_end.isoformat(),
    }

    return {
        "base_date": base_date.isoformat(),
        "generated_at_jst": datetime.now(
            JST
        ).isoformat(),
        "evaluation_status": "ok",
        "results": [result],
    }


def write_json_atomic(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_name(
        path.name + ".tmp"
    )

    try:
        temp.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()



def main():
    try:
        base_date, cutoff = get_base_date_and_cutoff()
    except RuntimeError as exc:
        message = str(exc)


        if message.startswith(
            "Pre-open evaluation time has not arrived:"
        ):
            print(
                "[MARKET DATA NOT READY]",
                message,
                flush=True,
            )
            raise RuntimeError(
                "MARKET_DATA_NOT_READY: "
                "official evaluation cutoff "
                "has not arrived; "
                "existing market JSON must not "
                "be treated as newly generated"
            ) from exc

        raise

    print(
        "BASE_DATE:",
        base_date.isoformat(),
    )
    print(
        "EVALUATION_CUTOFF:",
        cutoff.isoformat(),
    )


    payload = build_market_data(
        base_date,
        cutoff,
    )

    if payload.get("evaluation_status") != "ok":
        raise RuntimeError(
            "Market data validation failed; "
            "latest JSON will not be overwritten"
        )

    results = payload.get("results")

    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(
            "Market data results are invalid"
        )

    cme = results[0]

    if (
        cme.get("status") != "ok"
        or cme.get("usable") is not True
        or cme.get("evaluation_base_date")
        != base_date.isoformat()
    ):
        raise RuntimeError(
            "CME data is not eligible for official evaluation"
        )

    history_path = (
        HISTORY_DIR
        / f"market_data_{base_date.isoformat()}.json"
    )

    write_json_atomic(
        history_path,
        payload,
    )
    write_json_atomic(
        OUTPUT,
        payload,
    )

    print(
        "MARKET DATA STATUS:",
        payload["evaluation_status"],
    )
    print(
        "MARKET DATA READY:",
        base_date.isoformat(),
    )


if __name__ == "__main__":
    main()
