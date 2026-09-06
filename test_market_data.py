"""
市場データ取得の単体テスト。

まず日経225先物 NIY=F が
yfinanceから正常に取得できるか確認する。

この段階では鮮度判定や
正常・異常の最終判定は行わない。
取得したDataFrameの構造を確認する。
"""

import pandas as pd

from market_data.providers import fetch_yfinance


def main():
    symbol = "NIY=F"

    print("=== Market Data Test ===")
    print()
    print("Symbol:", symbol)
    print("Fetching...")

    try:
        df = fetch_yfinance(
            symbol
        )

        print()
        print("=== SUCCESS ===")

        print()
        print("=== DataFrame Type ===")
        print(type(df))

        print()
        print("=== Row Count ===")
        print(len(df))

        print()
        print("=== Columns ===")
        print(df.columns.tolist())

        print()
        print("=== Index Type ===")
        print(type(df.index))

        print()
        print("=== Latest Timestamp ===")
        print(df.index[-1])

        print()
        print("=== Latest Row ===")
        print(df.tail(1))

        print()
        print("=== Last 5 Rows ===")
        print(df.tail())

        # 最低限の構造チェック
        required_columns = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            raise RuntimeError(
                f"{symbol}: missing columns "
                f"{missing_columns}"
            )

        if not isinstance(
            df.index,
            pd.DatetimeIndex,
        ):
            raise RuntimeError(
                f"{symbol}: index is not DatetimeIndex"
            )

        print()
        print("=== STRUCTURE CHECK PASSED ===")

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