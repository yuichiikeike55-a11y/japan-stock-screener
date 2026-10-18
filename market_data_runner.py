import json
import os

from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

BASE_DATE_TEXT = os.getenv(
    "BASE_DATE",
    "",
).strip()

if BASE_DATE_TEXT:
    BASE_DATE = datetime.strptime(
        BASE_DATE_TEXT,
        "%Y-%m-%d",
    ).date()
else:
    BASE_DATE = datetime.now(JST).date()

EVALUATION_CUTOFF = datetime.combine(
    BASE_DATE,
    time(20, 30),
    tzinfo=JST,
)
if BASE_DATE > datetime.now(JST).date():
    raise RuntimeError(
        f"Future BASE_DATE is not allowed: "
        f"{BASE_DATE.isoformat()} "
        f"current_jst_date={datetime.now(JST).date().isoformat()}"
    )

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
    # Futures evaluation cutoff validation
    # =====================================

    for result in results:
        as_of_text = result.get("as_of")

        if not as_of_text:
            raise RuntimeError(
                f"Missing futures as_of: {result.get('key')}"
            )

        as_of_jst = datetime.fromisoformat(
            as_of_text
        ).astimezone(JST)

        result["as_of_jst"] = (
            as_of_jst.isoformat()
        )

        result["evaluation_base_date"] = (
            BASE_DATE.isoformat()
        )

        result["evaluation_cutoff_jst"] = (
            EVALUATION_CUTOFF.isoformat()
        )

        if as_of_jst > EVALUATION_CUTOFF:
            result["status"] = "stale"
            result["reason"] = (
                "data_after_evaluation_cutoff"
            )

            raise RuntimeError(
                f"Futures data after cutoff: "
                f"{result['key']} "
                f"as_of={as_of_jst.isoformat()} "
                f"cutoff={EVALUATION_CUTOFF.isoformat()}"
            )

        if result.get("status") not in (
            "ok",
            "closed",
        ):
            raise RuntimeError(
                f"Futures data unavailable: "
                f"{result['key']} "
                f"status={result.get('status')}"
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
    # =====================================
    # Save dated futures snapshot
    # =====================================

    SNAPSHOT_DIR = OUTPUT_DIR / "market_data_history"

    SNAPSHOT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    snapshot_file = (
        SNAPSHOT_DIR
        / f"market_data_{BASE_DATE.isoformat()}.json"
    )

    if snapshot_file.exists():
        print(
            "Existing snapshot preserved:",
            snapshot_file,
        )
    else:
        with open(
            snapshot_file,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                output_data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            "Saved futures snapshot:",
            snapshot_file,
        )        
if __name__ == "__main__":
    main()
