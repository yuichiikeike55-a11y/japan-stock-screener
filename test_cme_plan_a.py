
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_data.normalizers import normalize_yfinance
from market_data.validators import validate_freshness


JST = ZoneInfo("Asia/Tokyo")
SYMBOL = "NKD=F"

# テスト専用の仮想日時・仮想価格
CUTOFF = datetime(2026, 11, 4, 6, 15, tzinfo=JST)


def sample_hourly():
    index = pd.DatetimeIndex(
        [
            "2026-11-04 03:00:00+09:00",
            "2026-11-04 04:00:00+09:00",
            "2026-11-04 05:00:00+09:00",
            "2026-11-04 06:00:00+09:00",
        ]
    )

    return pd.DataFrame(
        {"Close": [50000, 50100, 50200, 50300]},
        index=index,
    )


def sample_daily():
    index = pd.DatetimeIndex(
        ["2026-11-02", "2026-11-03"]
    )

    return pd.DataFrame(
        {"Close": [49500, 49900]},
        index=index,
    )


class TestCmePlanA(unittest.TestCase):

    def test_unfinished_bar_excluded(self):
        result = normalize_yfinance(
            SYMBOL,
            sample_hourly(),
            sample_daily(),
            cutoff=CUTOFF,
        )

        self.assertEqual(result["value"], 50200.0)
        self.assertEqual(
            result["bar_completed_jst"],
            "2026-11-04T06:00:00+09:00",
        )

    def test_fresh_completed_bar(self):
        result = normalize_yfinance(
            SYMBOL,
            sample_hourly(),
            sample_daily(),
            cutoff=CUTOFF,
        )

        validated = validate_freshness(
            result,
            max_age_minutes=180,
            now=CUTOFF,
        )

        self.assertEqual(validated["status"], "ok")
        self.assertIs(validated["usable"], True)
        self.assertEqual(validated["age_minutes"], 15.0)

    def test_stale_bar_rejected(self):
        result = normalize_yfinance(
            SYMBOL,
            sample_hourly(),
            sample_daily(),
            cutoff=CUTOFF,
        )

        later = datetime(
            2026, 11, 4, 10, 0, tzinfo=JST
        )

        validated = validate_freshness(
            result,
            max_age_minutes=180,
            now=later,
        )

        self.assertEqual(validated["status"], "stale")
        self.assertIs(validated["usable"], False)

    def test_missing_hourly_data_stops(self):
        with self.assertRaises(RuntimeError):
            normalize_yfinance(
                SYMBOL,
                pd.DataFrame(),
                sample_daily(),
                cutoff=CUTOFF,
            )

    def test_missing_daily_data_stops(self):
        with self.assertRaises(RuntimeError):
            normalize_yfinance(
                SYMBOL,
                sample_hourly(),
                pd.DataFrame(),
                cutoff=CUTOFF,
            )

    def test_no_completed_bar_stops(self):
        hourly = sample_hourly().iloc[[-1]]

        with self.assertRaises(RuntimeError):
            normalize_yfinance(
                SYMBOL,
                hourly,
                sample_daily(),
                cutoff=CUTOFF,
            )

    def test_future_timestamp_stops(self):
        result = normalize_yfinance(
            SYMBOL,
            sample_hourly(),
            sample_daily(),
            cutoff=CUTOFF,
        )

        earlier = datetime(
            2026, 11, 4, 5, 0, tzinfo=JST
        )

        with self.assertRaises(RuntimeError):
            validate_freshness(
                result,
                max_age_minutes=180,
                now=earlier,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
