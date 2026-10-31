
"""
CME日経225先物（NKD）の取引カレンダー。

公式スケジュールで個別確認した日付のみ登録する。
未登録日は安全のため評価を停止する。

注意:
- 自動的に休日・短縮取引日を判定するものではない。
- 取引時間の変更時には登録内容の再確認が必要。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")

# CME公式スケジュールで個別確認した取引日
# キー: CME取引日
# 値: 日本時間での取引終了日時
VERIFIED_SESSIONS = {
    "2026-10-30": "2026-10-31T06:00:00+09:00",
}


def get_verified_session_end(base_date: date) -> datetime:
    """
    確認済みのCME取引終了時刻を返す。
    未登録日・不正な日時は正式評価を停止する。
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
