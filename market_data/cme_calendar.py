
"""
CME日経225米ドル建て先物（NKD）カレンダー。

通常日:
  CME公式仕様の米国東部時間17:00を終了候補とする。
  CMESカレンダーが通常日のパターンと一致する場合のみ採用。

休場日・短縮取引日・不明日:
  正式評価を停止する。

注意:
  CMESはNKD専用カレンダーではない。
  特別取引日を完全に検出できる保証はない。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import exchange_calendars as xcals


JST = ZoneInfo("Asia/Tokyo")
EASTERN = ZoneInfo("America/New_York")

# 過去に個別確認した日付を保存
VERIFIED_SESSIONS = {
    "2026-10-30": "2026-10-31T06:00:00+09:00",
}


def get_regular_session_end(base_date: date) -> datetime:
    """NKD通常取引終了時刻の候補を計算する。"""
    eastern_end = datetime.combine(
        base_date,
        time(17, 0),
        tzinfo=EASTERN,
    )
    return eastern_end.astimezone(JST)


def get_verified_session_end(base_date: date) -> datetime:
    """
    NKD終了時刻を取得する。

    個別確認済み日付を優先する。
    その他はCMESの通常日パターンを照合する。
    """
    key = base_date.isoformat()

    if base_date.weekday() >= 5:
        raise RuntimeError(
            f"CME weekend trading date: {key}"
        )

    calendar = xcals.get_calendar("CMES")
    stamp = pd.Timestamp(key)

    if not calendar.is_session(stamp):
        raise RuntimeError(
            f"CME calendar closed: {key}"
        )

    regular_end = get_regular_session_end(base_date)

    cmes_close = calendar.session_close(stamp)
    cmes_close_jst = cmes_close.tz_convert(
        JST
    ).to_pydatetime()

    # 既存検証で確認したCMESとNKDの通常終了時刻差。
    expected_cmes_close = (
        regular_end + timedelta(hours=1)
    )

    if cmes_close_jst != expected_cmes_close:
        raise RuntimeError(
            "CME special or unknown session: "
            f"date={key}, "
            f"cmes_close={cmes_close_jst.isoformat()}, "
            f"nkd_regular_end={regular_end.isoformat()}"
        )

    # 個別確認済みの時刻と計算結果が異なれば停止
    verified_raw = VERIFIED_SESSIONS.get(key)

    if verified_raw is not None:
        verified_end = datetime.fromisoformat(
            verified_raw
        )

        if verified_end.tzinfo is None:
            raise RuntimeError(
                f"CME verified timezone missing: {key}"
            )

        if verified_end.astimezone(JST) != regular_end:
            raise RuntimeError(
                f"CME verified session mismatch: {key}"
            )

    print(
        "[CME CALENDAR]",
        f"date={key}",
        "status=regular_candidate",
        f"nkd_end_jst={regular_end.isoformat()}",
        f"cmes_close_jst={cmes_close_jst.isoformat()}",
        flush=True,
    )

    return regular_end
