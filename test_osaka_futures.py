from market_data.providers import (
    fetch_yahoo_japan_osaka_futures,
)
from market_data.normalizers import (
    normalize_yahoo_japan_osaka,
)

def main():
    print(
        "=== Osaka Nikkei 225 Futures "
        "Provider Test ==="
    )

    data = (
        fetch_yahoo_japan_osaka_futures()
    )
    normalized = (
        normalize_yahoo_japan_osaka(
            data
        )
    )
    print()
    print("=== RESULT ===")

    for key, value in data.items():
        print(
            f"{key}: {value}"
        )
    print()
    print("=== NORMALIZED RESULT ===")

    for key, value in normalized.items():
        print(
            f"{key}: {value}"
        )
        
    required = [
        "symbol",
        "source",
        "value",
        "change",
        "change_pct",
        "quote_time",
        "previous_close",
        "previous_close_date",
        "open",
        "high",
        "low",
        "volume",
    ]

    missing = [
        key
        for key in required
        if data.get(key) is None
    ]

    if missing:
        raise RuntimeError(
            f"Missing fields: {missing}"
        )

    print()
    print(
        "SUCCESS: Osaka futures provider"
    )


if __name__ == "__main__":
    main()
