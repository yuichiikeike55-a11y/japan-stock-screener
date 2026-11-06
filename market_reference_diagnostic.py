
import json
import math
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT = Path("output")
SOURCE = OUTPUT / "market_data_reference_latest.json"
TARGET = OUTPUT / "market_reference_diagnostic_latest.json"

def main():
    if not SOURCE.is_file():
        raise RuntimeError("STOP: reference market JSON missing")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    base_date = os.environ.get("BASE_DATE", "").strip()

    if not base_date:
        raise RuntimeError("STOP: BASE_DATE missing")

    if data.get("base_date") != base_date:
        raise RuntimeError("STOP: reference base date mismatch")

    if data.get("evaluation_status") != "reference_only":
        raise RuntimeError("STOP: invalid reference status")

    if data.get("official_publication_allowed") is not False:
        raise RuntimeError("STOP: official publication flag invalid")

    rows = data.get("results")
    if not isinstance(rows, list):
        raise RuntimeError("STOP: reference results invalid")

    matches = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("key") == "nikkei225_futures_cme"
    ]

    if len(matches) != 1:
        raise RuntimeError("STOP: CME reference missing or duplicated")

    cme = matches[0]

    if (
        cme.get("status") != "ok"
        or cme.get("reference_usable") is not True
        or cme.get("usable") is not False
        or cme.get("contract_month_verified") is not False
    ):
        raise RuntimeError("STOP: CME reference quality invalid")

    for key in ("value", "previous_close", "change_pct"):
        value = cme.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise RuntimeError(f"STOP: invalid {key}")

    change_pct = float(cme["change_pct"])
    calculated = (
        float(cme["value"]) / float(cme["previous_close"]) - 1
    ) * 100

    if float(cme["previous_close"]) <= 0 or float(cme["value"]) <= 0:
        raise RuntimeError("STOP: invalid CME price")

    if abs(change_pct - calculated) > 0.01:
        raise RuntimeError("STOP: CME percentage inconsistent")

    # 参考データの異常値警告。未検証なので正式採点はしない。
    warnings = ["contract_month_unverified"]

    if abs(change_pct) >= 5:
        warnings.append("large_futures_change_requires_review")

    result = {
        "base_date": base_date,
        "generated_at": datetime.now(
            ZoneInfo("Asia/Tokyo")
        ).isoformat(),
        "evaluation_status": "reference_only",
        "publication_status": "diagnostic",
        "official_publication_allowed": False,
        "market_score": None,
        "market_score_max": 15,
        "reference_cme": {
            "value": cme["value"],
            "previous_close": cme["previous_close"],
            "change_pct": change_pct,
            "contract_month_verified": False,
        },
        "quality_warnings": warnings,
        "reason": "CME contract month not verified",
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "[REFERENCE DIAGNOSTIC READY]",
        f"base_date={base_date}",
        f"change_pct={change_pct:.4f}",
        f"warnings={warnings}",
        flush=True,
    )

if __name__ == "__main__":
    main()
