
"""
東証の基準日判定テスト
本番ファイル・公開結果は変更しない。
"""

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


JST = ZoneInfo("Asia/Tokyo")


def expected_base_date(now_jst):
    """
    本番ワークフローの朝の運用に合わせ、
    JST当日より前の直近東証営業日を返す。
    """
    if now_jst.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")

    now_jst = now_jst.astimezone(JST)
    calendar = xcals.get_calendar("XTKS")

    today = pd.Timestamp(now_jst.date())
    previous = calendar.date_to_session(
        today,
        direction="previous",
    )

    # 当日が営業日の場合も、朝の実行では前営業日を選ぶ
    if previous.date() == now_jst.date():
        previous = calendar.previous_session(previous)

    return previous.date()


class TestBaseDate(unittest.TestCase):

    def test_november_2_morning(self):
        now = datetime(2026, 11, 2, 6, 15, tzinfo=JST)
        self.assertEqual(
            expected_base_date(now),
            date(2026, 10, 30),
        )

    def test_november_3_holiday(self):
        now = datetime(2026, 11, 3, 6, 15, tzinfo=JST)
        self.assertEqual(
            expected_base_date(now),
            date(2026, 11, 2),
        )

    def test_november_4_morning(self):
        now = datetime(2026, 11, 4, 6, 15, tzinfo=JST)
        self.assertEqual(
            expected_base_date(now),
            date(2026, 11, 2),
        )

    def test_november_4_before_seven(self):
        now = datetime(2026, 11, 4, 6, 59, tzinfo=JST)
        self.assertEqual(
            expected_base_date(now),
            date(2026, 11, 2),
        )

    def test_weekend(self):
        now = datetime(2026, 11, 7, 6, 15, tzinfo=JST)
        self.assertEqual(
            expected_base_date(now),
            date(2026, 11, 6),
        )

    def test_naive_datetime_rejected(self):
        now = datetime(2026, 11, 4, 6, 15)
        with self.assertRaises(ValueError):
            expected_base_date(now)


if __name__ == "__main__":
    unittest.main(verbosity=2)
