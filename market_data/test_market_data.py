"""
市場データ取得の単体テスト。

まず日経225先物 NIY=F が
yfinanceから正常に取得できるか確認する。
"""

from market_data.providers import fetch_yfinance


def main():
    symbol = "NIY=F"

    print("=== Market Data Test ===")
    print()
    print("Symbol:", symbol)
    print("Fetching...")

    try:
        result = fetch_yfinance(
            symbol
        )

        print()
        print("=== SUCCESS ===")

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