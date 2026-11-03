
"""
GitHub Actions 公開ゲートの独立テスト。

本番ファイルやoutputを変更しない。
ワークフロー内の最終ゲートと同じ判定条件を再現する。
"""

import unittest


REQUIRED_CHECKS = (
    "market_update",
    "market_validation",
    "sector_update",
    "sector_validation",
    "screener",
    "screening_validation",
)


def publication_ready(checks):
    return all(
        checks.get(name) == "success"
        for name in REQUIRED_CHECKS
    )


class TestPublicationGate(unittest.TestCase):

    def setUp(self):
        self.success = {
            name: "success"
            for name in REQUIRED_CHECKS
        }

    def test_all_success(self):
        self.assertTrue(
            publication_ready(self.success)
        )

    def test_market_update_failure(self):
        checks = self.success.copy()
        checks["market_update"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_market_validation_failure(self):
        checks = self.success.copy()
        checks["market_validation"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_sector_update_failure(self):
        checks = self.success.copy()
        checks["sector_update"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_sector_validation_failure(self):
        checks = self.success.copy()
        checks["sector_validation"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_screener_failure(self):
        checks = self.success.copy()
        checks["screener"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_screening_validation_failure(self):
        checks = self.success.copy()
        checks["screening_validation"] = "failure"
        self.assertFalse(publication_ready(checks))

    def test_skipped_validation(self):
        checks = self.success.copy()
        checks["screening_validation"] = "skipped"
        self.assertFalse(publication_ready(checks))

    def test_missing_status(self):
        checks = self.success.copy()
        del checks["market_validation"]
        self.assertFalse(publication_ready(checks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
