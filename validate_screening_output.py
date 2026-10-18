
import json
import math
import os
import sys
from pathlib import Path

FILE = Path("output/strategy_hits_latest.json")


def fail(message):
    print("VALIDATION FAILED:", message)
    sys.exit(1)


def main():
    if not FILE.is_file():
        fail(f"missing file: {FILE}")

    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read JSON: {exc}")

    if not isinstance(data, dict):
        fail("JSON root must be an object")

    base_date = data.get("base_date")
    requested_date = os.environ.get("BASE_DATE", "").strip()

    if not isinstance(base_date, str) or not base_date:
        fail("base_date missing")

    if requested_date and base_date != requested_date:
        fail(
            f"base date mismatch: {base_date} != {requested_date}"
        )

    if data.get("strategy_count") != 4:
        fail("strategy_count must be 4")

    rows = data.get("results")

    if not isinstance(rows, list):
        fail("results must be a list")

    count = data.get("unique_stock_count")

    if not isinstance(count, int) or isinstance(count, bool):
        fail("invalid unique_stock_count")

    if count != len(rows):
        fail("unique_stock_count does not match results")

    # 0件は異常と断定せず、公開を停止して確認する
    if count == 0:
        fail("zero hits: manual review required before publishing")

    codes = set()

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            fail(f"row {index}: invalid structure")

        code = str(row.get("code", "")).strip()

        if not code or code in codes:
            fail(f"row {index}: missing or duplicate code")

        codes.add(code)

        if row.get("base_date") != base_date:
            fail(f"{code}: stock base date mismatch")

        if row.get("hit_count", 0) < 1:
            fail(f"{code}: no strategy hit")

        market = row.get("market_evaluation")
        sector = row.get("sector_evaluation")
        final = row.get("final_evaluation")

        for name, section in [
            ("market", market),
            ("sector", sector),
            ("final", final),
        ]:
            if not isinstance(section, dict):
                fail(f"{code}: {name} evaluation missing")

            if section.get("evaluation_status") != "ok":
                fail(f"{code}: {name} evaluation not ok")

        if sector.get("sector_base_date") != base_date:
            fail(f"{code}: sector base date mismatch")

        if sector.get("sector_count") != 18:
            fail(f"{code}: sector count mismatch")

        futures = market.get("futures")

        if not isinstance(futures, dict):
            fail(f"{code}: futures data missing")

        cme = futures.get("cme")

        if not isinstance(cme, dict):
            fail(f"{code}: CME data missing")

        if cme.get("usable") is not True:
            fail(f"{code}: CME unusable")

        if cme.get("status") != "ok":
            fail(f"{code}: CME status not ok")

        change = cme.get("change_pct")

        if (
            isinstance(change, bool)
            or not isinstance(change, (int, float))
            or not math.isfinite(change)
        ):
            fail(f"{code}: CME change_pct invalid")

        score = final.get("final_score")

        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 100
        ):
            fail(f"{code}: invalid final score")

        if final.get("final_rank") not in (
            "S", "A", "B", "C", "D", "E"
        ):
            fail(f"{code}: invalid final rank")

    print("VALIDATION PASSED")
    print("Base date:", base_date)
    print("Strategies:", data["strategy_count"])
    print("Sectors: 18 (confirmed in hit evaluations)")
    print("Final evaluations:", len(rows))
    print("CME: usable in all evaluated stocks")


if __name__ == "__main__":
    main()
