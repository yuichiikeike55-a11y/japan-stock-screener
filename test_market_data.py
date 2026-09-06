"""
日足市場データ取得テスト。

NIY=Fの日足をyfinanceから取得し、
前日終値判定に使えるデータ構造か確認する。
"""

import pandas as pd

from market_data.providers import fetch_yfinance_daily


def main():
    symbol = "NIY=F"

    print("=== Daily Market Data Test ===")
    print()
    print("Symbol:", symbol)
    print("Fetching daily data...")

    try:
        df = fetch_yfinance_daily(
            symbol
        )

        print()
        print("=== FETCH SUCCESS ===")

        print(
            "rows:",
            len(df),
        )

        print()
        print("=== Columns ===")
        print(
            df.columns.tolist()
        )

        print()
        print("=== Index Type ===")
        print(
            type(df.index)
        )

        print()
        print("=== Last 5 Daily Rows ===")
        print(
            df.tail()
        )

        print()
        print("=== Latest Daily Date ===")
        print(
            df.index[-1]
        )

        print()
        print("=== Latest Daily Close ===")
        print(
            float(
                df.iloc[-1]["Close"]
            )
        )

        if len(df) >= 2:
            print()
            print(
                "=== Previous Daily Date ==="
            )
            print(
                df.index[-2]
            )

            print()
            print(
                "=== Previous Daily Close ==="
            )
            print(
                float(
                    df.iloc[-2]["Close"]
                )
            )

        # 最低限の構造確認
        if "Close" not in df.columns:
            raise RuntimeError(
                f"{symbol}: Close column is missing"
            )

        if not isinstance(
            df.index,
            pd.DatetimeIndex,
        ):
            raise RuntimeError(
                f"{symbol}: index is not DatetimeIndex"
            )

        if len(df) < 2:
            raise RuntimeError(
                f"{symbol}: not enough daily data"
            )

        print()
        print(
            "=== DAILY DATA CHECK PASSED ==="
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