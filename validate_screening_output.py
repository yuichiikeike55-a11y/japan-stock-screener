
"""
4戦略スクリーニング最終出力検証。

正式評価:
    5項目がすべて正常であること。

暫定評価:
    地合い・セクターの欠損だけを許容。
    欠損理由を明記し、最高ランクB。

共通:
    基準日不一致データは使用不可。
    個別株の必須評価欠損は不可。
    0件ヒットは公開停止。
"""

import json
import math
import os
import sys
from datetime import date
from pathlib import Path


FILE = Path("output/strategy_hits_latest.json")

LIMITS = {
    "strategy_fit": 35,
    "sector": 25,
    "technical": 15,
    "market": 15,
    "volume_supply": 10,
}

SECTIONS = {
    "strategy_fit": (
        "strategy_fit_evaluation",
        "strategy_fit_score",
    ),
    "sector": (
        "sector_evaluation",
        "sector_score",
    ),
    "technical": (
        "technical_evaluation",
        "technical_score",
    ),
    "market": (
        "market_evaluation",
        "market_score",
    ),
    "volume_supply": (
        "volume_supply_evaluation",
        "volume_supply_score",
    ),
}


def fail(message):
    print("VALIDATION FAILED:", message)
    sys.exit(1)


def number(value, low=0, high=100):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and low <= value <= high
    )


def rank_from_score(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "E"


def cap_rank(rank, maximum):
    order = ["S", "A", "B", "C", "D", "E"]
    return order[max(
        order.index(rank),
        order.index(maximum),
    )]


def check_date(value, expected, label):
    if not isinstance(value, str):
        fail(f"{label}: date missing")

    try:
        actual = date.fromisoformat(value)
    except ValueError:
        fail(f"{label}: invalid date")

    if actual.isoformat() != expected:
        fail(
            f"{label}: date mismatch "
            f"{actual} != {expected}"
        )


def check_row(row, base_date, index):
    if not isinstance(row, dict):
        fail(f"row {index}: invalid structure")

    code = str(row.get("code", "")).strip()

    if not code:
        fail(f"row {index}: code missing")

    check_date(
        row.get("base_date"),
        base_date,
        f"{code} stock",
    )

    hits = row.get("hit_count")

    if (
        not isinstance(hits, int)
        or isinstance(hits, bool)
        or not 1 <= hits <= 4
    ):
        fail(f"{code}: invalid hit_count")

    stock_metrics = row.get("metrics")

    if not isinstance(stock_metrics, dict):
        fail(f"{code}: stock metrics missing")

    if stock_metrics.get("base_date") is not None:
        check_date(
            str(stock_metrics["base_date"])[:10],
            base_date,
            f"{code} metrics",
        )

    final = row.get("final_evaluation")

    if not isinstance(final, dict):
        fail(f"{code}: final evaluation missing")

    status = final.get("evaluation_status")

    if status not in ("ok", "provisional"):
        fail(f"{code}: final status invalid: {status}")

    breakdown = final.get("score_breakdown")

    if not isinstance(breakdown, dict):
        fail(f"{code}: score breakdown missing")

    missing = []

    for key, (section_name, score_name) in SECTIONS.items():
        section = row.get(section_name)

        if not isinstance(section, dict):
            fail(f"{code}: {section_name} missing")

        section_status = section.get("evaluation_status")
        value = section.get(score_name)

        if section_status == "ok":
            if not number(value, 0, LIMITS[key]):
                fail(f"{code}: invalid {score_name}")

            if not number(
                breakdown.get(key),
                0,
                LIMITS[key],
            ):
                fail(f"{code}: invalid breakdown {key}")

            if abs(breakdown[key] - value) > 0.11:
                fail(f"{code}: {key} score mismatch")

        elif (
            status == "provisional"
            and key in ("market", "sector")
        ):
            missing.append(key)

            if breakdown.get(key) != 0:
                fail(
                    f"{code}: unavailable {key} "
                    "must contribute zero"
                )

        else:
            fail(
                f"{code}: required evaluation "
                f"not ok: {key}"
            )

    sector = row["sector_evaluation"]
    market = row["market_evaluation"]

    if sector.get("evaluation_status") == "ok":
        sector_date = sector.get(
            "sector_base_date",
            sector.get("base_date"),
        )

        check_date(
            sector_date,
            base_date,
            f"{code} sector",
        )

        if sector.get("sector_count") != 18:
            fail(f"{code}: sector count is not 18")

    if market.get("evaluation_status") == "ok":
        futures = market.get("futures")

        if not isinstance(futures, dict):
            fail(f"{code}: futures missing")

        usable_futures = [
            item for item in futures.values()
            if (
                isinstance(item, dict)
                and item.get("usable") is True
                and item.get("status") in ("ok", "closed")
                and number(
                    item.get("change_pct"),
                    -1000,
                    1000,
                )
            )
        ]

        if not usable_futures:
            fail(f"{code}: no verified usable futures")

    score = final.get("final_score")
    rank = final.get("final_rank")

    if not number(score, 0, 100):
        fail(f"{code}: invalid final score")

    if rank not in ("S", "A", "B", "C", "D", "E"):
        fail(f"{code}: invalid final rank")

    bonus = final.get("multi_strategy_bonus", 0)

    if not number(bonus, 0, 3):
        fail(f"{code}: invalid bonus")

    if bonus > hits - 1:
        fail(f"{code}: bonus exceeds hit count")

    expected_score = min(
        100,
        sum(breakdown[key] for key in LIMITS) + bonus,
    )

    if abs(score - expected_score) > 0.11:
        fail(
            f"{code}: final score mismatch "
            f"{score} != {expected_score}"
        )

    expected_rank = rank_from_score(score)

    safety = final.get("safety", {})

    if not isinstance(safety, dict):
        fail(f"{code}: safety missing")

    quality_warning = (
        safety.get("data_quality_warning") is True
        or stock_metrics.get("data_quality_status")
        == "warning"
        or sector.get("data_quality_status")
        == "warning"
    )

    if quality_warning:
        expected_rank = cap_rank(expected_rank, "B")

    if safety.get("strategy_negated") is True:
        expected_rank = cap_rank(expected_rank, "C")

    if status == "provisional":
        if not missing:
            fail(f"{code}: provisional without missing data")

        expected_rank = cap_rank(expected_rank, "B")

        recorded_missing = final.get("missing_components")

        if not isinstance(recorded_missing, list):
            fail(f"{code}: missing_components absent")

        if set(recorded_missing) != set(missing):
            fail(f"{code}: missing_components mismatch")

    elif missing:
        fail(f"{code}: official evaluation has missing data")

    if rank != expected_rank:
        fail(
            f"{code}: rank mismatch "
            f"{rank} != {expected_rank}"
        )

    return code, status


def main():
    if not FILE.is_file():
        fail(f"missing file: {FILE}")

    try:
        data = json.loads(
            FILE.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        fail(f"cannot read JSON: {exc}")

    if not isinstance(data, dict):
        fail("JSON root must be an object")

    base_date = data.get("base_date")

    if not isinstance(base_date, str):
        fail("base_date missing")

    check_date(base_date, base_date, "output")

    requested = os.getenv("BASE_DATE", "").strip()

    if requested:
        check_date(base_date, requested, "output")

    if data.get("strategy_count") != 4:
        fail("strategy_count must be 4")

    rows = data.get("results")

    if not isinstance(rows, list):
        fail("results must be a list")

    count = data.get("unique_stock_count")

    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(rows)
    ):
        fail("invalid unique_stock_count")

    if count == 0:
        fail("zero hits: manual review required")

    codes = set()
    official = 0
    provisional = 0

    for index, row in enumerate(rows, 1):
        code, status = check_row(
            row, base_date, index
        )

        if code in codes:
            fail(f"duplicate code: {code}")

        codes.add(code)

        if status == "ok":
            official += 1
        else:
            provisional += 1

    print("VALIDATION PASSED")
    print("Base date:", base_date)
    print("Strategies: 4")
    print("Hit stocks:", count)
    print("Official evaluations:", official)
    print("Provisional evaluations:", provisional)


if __name__ == "__main__":
    main()
