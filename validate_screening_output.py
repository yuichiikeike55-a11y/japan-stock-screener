
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT = Path("output")
JST = ZoneInfo("Asia/Tokyo")


def stop(message):
    print("SCREENING VALIDATION FAILED:", message)
    sys.exit(1)


def load_json(filename):
    path = OUTPUT / filename

    if not path.is_file():
        stop(f"missing file: {path}")

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        stop(f"invalid JSON: {path}: {exc}")

    if not isinstance(data, dict):
        stop(f"invalid JSON structure: {path}")

    return data


def expected_base_date():
    value = os.environ.get("BASE_DATE", "").strip()

    if value:
        try:
            return datetime.strptime(
                value, "%Y-%m-%d"
            ).date().isoformat()
        except ValueError:
            stop(f"invalid BASE_DATE: {value}")

    return datetime.now(JST).date().isoformat()


def main():
    base_date = expected_base_date()

    market = load_json("market_data.json")
    sectors = load_json("sector_indices_latest.json")
    hits = load_json("strategy_hits_latest.json")

    if market.get("evaluation_base_date") != base_date:
        stop("market base date mismatch")

    if sectors.get("latest_base_date") != base_date:
        stop("sector base date mismatch")

    if sectors.get("sector_count") != 18:
        stop("sector count is not 18")

    if sectors.get("processed_count") != 18:
        stop("sector processed count is not 18")

    if sectors.get("failure_count") != 0:
        stop("sector failures detected")

    sector_rows = sectors.get("results")

    if not isinstance(sector_rows, list):
        stop("sector results are missing")

    if len(sector_rows) != 18:
        stop("sector results count is not 18")

    for row in sector_rows:
        if not isinstance(row, dict):
            stop("invalid sector row")

        if row.get("base_date") != base_date:
            stop("individual sector base date mismatch")

    if not hits:
        stop("strategy hits JSON is empty")

    print("SCREENING VALIDATION PASSED")
    print("Base date:", base_date)
    print("Sectors:", len(sector_rows))


if __name__ == "__main__":
    main()
