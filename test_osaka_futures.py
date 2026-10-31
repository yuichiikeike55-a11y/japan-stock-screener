
"""
大阪先物の旧Yahoo取得方法が
正式評価に使用されないことを確認するテスト。

正式な市場評価はCME先物を使用する。
"""

from market_data.providers import (
    fetch_yahoo_japan_osaka_futures,
)


def main():
    print(
        "=== Osaka Legacy Provider "
        "Disabled Test ==="
    )

    try:
        fetch_yahoo_japan_osaka_futures()

    except RuntimeError as exc:
        message = str(exc)

        if (
            "Osaka futures Yahoo source is disabled"
            not in message
        ):
            raise AssertionError(
                "Unexpected Osaka provider error: "
                f"{message}"
            ) from exc

        print(
            "PASS: Osaka Yahoo provider "
            "is disabled"
        )
        return

    raise AssertionError(
        "FAIL: Disabled Osaka Yahoo provider "
        "returned without an error"
    )


if __name__ == "__main__":
    main()
