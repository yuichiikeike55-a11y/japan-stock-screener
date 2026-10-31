
"""
CME日経225米ドル建て先物（NKD）の取引カレンダー。

通常取引終了時刻は米国東部時間17:00から計算する。
ただし、公式確認済みの日付のみ正式評価を許可する。

未確認日・休場日・短縮取引日の未確認データは停止する。
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
EASTERN = ZoneInfo("America/New_York")

# CME公式スケジュールで個別確認した取引日
# 値は日本時間での終了日時
VERIFIED_SESSIONS = {
    "2026-10-30": "2026-10-31T06:00:00+09:00",
}


def get_regular_session_end(base_date: date) -> datetime:
    """
    通常取引終了時刻を日本時間で返す。
    米国夏時間・冬時間の切り替えに対応。
    休日・短縮取引日は判定しない。
    """
    eastern_end = datetime.combine(
        base_date,
        time(17, 0),
        tzinfo=EASTERN,
    )
    return eastern_end.astimezone(JST)


def get_verified_session_end(base_date: date) -> datetime:
    """
    公式確認済みの日付だけ終了時刻を返す。
    未登録日は正式評価を停止する。
    """
    key = base_date.isoformat()
    raw = VERIFIED_SESSIONS.get(key)

    if raw is None:
        raise RuntimeError(
            f"CME session calendar not verified: {key}"
        )

    session_end = datetime.fromisoformat(raw)

    if session_end.tzinfo is None:
        raise RuntimeError(
            f"CME session end timezone missing: {key}"
        )

    return session_end.astimezone(JST)
