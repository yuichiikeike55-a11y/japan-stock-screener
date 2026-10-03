from market_data.providers import (
    fetch_yfinance,
    fetch_yfinance_daily,
)

from market_data.normalizers import (
    normalize_yfinance,
)

from market_data.validators import (
    validate_freshness,
)

def main():
    symbol = "NKD=F"

    print(
        "=== CME Nikkei 225 Futures "
        "Provider Test ==="
    )

    print(
        "Symbol:",
        symbol
    )

    # =====================================
    # Provider
    # =====================================

    hourly = fetch_yfinance(
        symbol
    )

    daily = fetch_yfinance_daily(
        symbol
    )

    print()
    print("=== HOURLY DATA ===")
    print(
        hourly.tail()
    )

    print()
    print("=== DAILY DATA ===")
    print(
        daily.tail()
    )

    # =====================================
    # Normalizer
    # =====================================

    normalized = normalize_yfinance(
        symbol,
        hourly,
        daily,
    )
    validated = validate_freshness(
        normalized,
        180,
    )
    print()
    print("=== NORMALIZED RESULT ===")

    for key, value in normalized.items():
        print(
            f"{key}: {value}"
        )
    print()
    print("=== VALIDATED RESULT ===")

    for key, value in validated.items():
        print(
            f"{key}: {value}"
        )
    # =====================================
    # Required fields
    # =====================================

    required = [
        "symbol",
        "source",
        "value",
        "previous_close",
        "change",
        "change_pct",
        "as_of",
    ]

    missing = [
        key
        for key in required
        if normalized.get(key) is None
    ]

    if missing:
        raise RuntimeError(
            f"Missing fields: {missing}"
        )

    print()
    print(
        "SUCCESS: CME futures provider"
    )


if __name__ == "__main__":
    main()
