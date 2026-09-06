"""
市場データ取得・標準化テスト。

NIY=Fについて、
1時間足から最新値、
日足から前営業日終値を取得し、
共通市場データ形式へ変換できるか確認する。
"""

from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)

from market_data.normalizers import (
    normalize_yfinance,
)


def main():
    symbol = "NIY=F"

    print("=== Market Data Full Test ===")
    print()
    print("Symbol:", symbol)

    try:
        # =====================================
        # データ取得
        # =====================================

        print()
        print("Fetching hourly data...")

        hourly_df = fetch_yfinance(
            symbol
        )

        print(
            "hourly rows:",
            len(hourly_df),
        )

        print()
        print("Fetching daily data...")

        daily_df = fetch_yfinance_daily(
            symbol
        )

        print(
            "daily rows:",
            len(daily_df),
        )

        # =====================================
        # 標準化
        # =====================================

        result = normalize_yfinance(
            symbol,
            hourly_df,
            daily_df,
        )

        print()
        print("=== NORMALIZE RESULT ===")

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

        # =====================================
        # 前日比計算チェック
        # =====================================

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

        expected_change_pct = (
            expected_change
            / result["previous_close"]
            * 100
        )

        if abs(
            result["change_pct"]
            - expected_change_pct
        ) > 0.000001:
            raise RuntimeError(
                "change_pct calculation mismatch"
            )

        # =====================================
        # 前営業日選択チェック
        # =====================================

        latest_date = (
            hourly_df.index[-1].date()
        )

        previous_rows = (
            daily_df[
                daily_df.index.map(
                    lambda x:
                        x.date()
                        < latest_date
                )
            ]
        )

        if previous_rows.empty:
            raise RuntimeError(
                "previous daily row not found"
            )

        expected_previous_close = float(
            previous_rows.iloc[-1]["Close"]
        )

        if abs(
            result["previous_close"]
            - expected_previous_close
        ) > 0.000001:
            raise RuntimeError(
                "previous_close selection mismatch"
            )

        print()
        print(
            "=== FULL CHECK PASSED ==="
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