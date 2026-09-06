"""
市場データ取得・標準化の単体テスト。

NIY=Fをyfinanceから取得し、
共通市場データ形式へ正常に
変換できるか確認する。
"""

from market_data.providers import fetch_yfinance
from market_data.normalizers import normalize_yfinance


def main():
    symbol = "NIY=F"

    print("=== Market Data Normalize Test ===")
    print()
    print("Symbol:", symbol)
    print("Fetching...")

    try:
        df = fetch_yfinance(
            symbol
        )

        print()
        print("=== FETCH SUCCESS ===")
        print(
            "rows:",
            len(df),
        )

        result = normalize_yfinance(
            symbol,
            df,
        )

        print()
        print("=== NORMALIZE SUCCESS ===")

        print(
            "symbol:",
            result["symbol"],
        )

        print(
            "source:",
            result["source"],
        )

        print(
            "value:",
            result["value"],
        )

        print(
            "previous_close:",
            result["previous_close"],
        )

        print(
            "change:",
            result["change"],
        )

        print(
            "change_pct:",
            result["change_pct"],
        )

        print(
            "as_of:",
            result["as_of"],
        )

        # =====================================
        # 基本整合性チェック
        # =====================================

        required_keys = [
            "symbol",
            "source",
            "value",
            "previous_close",
            "change",
            "change_pct",
            "as_of",
        ]

        missing_keys = [
            key
            for key in required_keys
            if key not in result
        ]

        if missing_keys:
            raise RuntimeError(
                f"missing keys: {missing_keys}"
            )

        if result["symbol"] != symbol:
            raise RuntimeError(
                "symbol mismatch"
            )

        if result["source"] != "yfinance":
            raise RuntimeError(
                "source mismatch"
            )

        expected_change = (
            result["value"]
            - result["previous_close"]
        )

        if abs(
            result["change"]
            - expected_change
        ) > 0.000001:
            raise RuntimeError(
                "change calculation mismatch"
            )

        print()
        print(
            "=== NORMALIZE CHECK PASSED ==="
        )

    except Exception as e:
        print()
        print("=== FAILED ===")
        print(
            "error:",
            repr(e),
        )

        raise


if __name__ == "__main__":
    main()