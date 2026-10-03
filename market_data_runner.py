import json
from pathlib import Path

from market_data.providers import (
    fetch_yahoo_japan_osaka_futures,
    fetch_yfinance,
    fetch_yfinance_daily,
)

from market_data.normalizers import (
    normalize_yahoo_japan_osaka,
    normalize_yfinance,
)

from market_data.validators import (
    validate_freshness,
)
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "market_data.json"
def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    results = []
    # =====================================
    # Osaka Nikkei 225 Futures
    # =====================================

    osaka_raw = (
        fetch_yahoo_japan_osaka_futures()
    )

    osaka_normalized = (
        normalize_yahoo_japan_osaka(
            osaka_raw
        )
    )

    osaka_validated = (
        validate_freshness(
            osaka_normalized,
            180,
        )
    )

    osaka_result = {
        "key": "nikkei225_futures_osaka",
        "name": "日経225先物（大阪）",
        "category": "futures",
        **osaka_validated,
    }

    results.append(
        osaka_result
    )  
    # =====================================
    # CME Nikkei 225 Futures
    # =====================================

    cme_symbol = "NKD=F"

    cme_hourly = fetch_yfinance(
        cme_symbol
    )

    cme_daily = fetch_yfinance_daily(
        cme_symbol
    )

    cme_normalized = normalize_yfinance(
        cme_symbol,
        cme_hourly,
        cme_daily,
    )

    cme_validated = validate_freshness(
        cme_normalized,
        180,
    )

    cme_result = {
        "key": "nikkei225_futures_cme",
        "name": "日経225先物（CME）",
        "category": "futures",
        **cme_validated,
    }

    results.append(
        cme_result
    )
    # =====================================
    # Save JSON
    # =====================================

    output_data = {
        "results": results,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output_data,
            f,
            ensure_ascii=False,
            indent=2,
        )
if __name__ == "__main__":
    main()
