
"""
4戦略スクリーニング出力検証。

official:
    正式ランキングを検証する。
    5項目すべて正常で、正式点数・ランクが必要。

diagnostic:
    当日診断結果を検証する。
    欠損銘柄は正式点数・ランクを持たない。
    診断成功は正式公開の許可を意味しない。
"""

import json
import math
import os
import sys
from datetime import date
from pathlib import Path

OFFICIAL_FILE = Path("output/strategy_hits_latest.json")
DIAGNOSTIC_FILE = Path(
    "output/strategy_hits_diagnostic_latest.json"
)

LIMITS = {
    "strategy_fit": 35,
    "sector": 25,
    "technical": 15,
    "market": 15,
    "volume_supply": 10,
}

SECTIONS = {
    "strategy_fit": ("strategy_fit_evaluation", "strategy_fit_score"),
    "sector": ("sector_evaluation", "sector_score"),
    "technical": ("technical_evaluation", "technical_score"),
    "market": ("market_evaluation", "market_score"),
    "volume_supply": (
        "volume_supply_evaluation", "volume_supply_score"
    ),
}


def fail(message):
    print("VALIDATION FAILED:", message, flush=True)
    sys.exit(1)


def number(value, low, high):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and low <= value <= high
    )


def check_date(value, expected, label):
    if not isinstance(value, str):
        fail(f"{label}: date missing")

    try:
        actual = date.fromisoformat(value).isoformat()
    except ValueError:
        fail(f"{label}: invalid date")

    if actual != expected:
        fail(f"{label}: date mismatch {actual} != {expected}")


def rank_from_score(score):
    for threshold, rank in (
        (90, "S"), (80, "A"), (70, "B"),
        (60, "C"), (50, "D"),
    ):
        if score >= threshold:
            return rank
    return "E"


def cap_rank(rank, maximum):
    order = ["S", "A", "B", "C", "D", "E"]
    return order[max(order.index(rank), order.index(maximum))]


def read_file(path):
    if not path.is_file():
        fail(f"missing file: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path}: {exc}")

    if not isinstance(data, dict):
        fail("JSON root must be an object")

    return data


def check_common(data, expected):
    base_date = data.get("base_date")
    check_date(base_date, expected, "output")

    if data.get("strategy_count") != 4:
        fail("strategy_count must be 4")

    rows = data.get("results")
    if not isinstance(rows, list):
        fail("results must be a list")

    count = data.get("unique_stock_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(rows)
    ):
        fail("invalid unique_stock_count")

    codes = set()

    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            fail(f"row {index}: invalid structure")

        code = str(row.get("code", "")).strip()
        if not code:
            fail(f"row {index}: code missing")
        if code in codes:
            fail(f"duplicate code: {code}")
        codes.add(code)

        if row.get("base_date") is not None:
            check_date(row["base_date"], expected, f"{code} stock")

        metrics = row.get("metrics")
        if isinstance(metrics, dict) and metrics.get("base_date"):
            check_date(
                str(metrics["base_date"])[:10],
                expected,
                f"{code} metrics",
            )

    return rows


def check_official_row(row):
    code = str(row["code"])
    final = row.get("final_evaluation")

    if not isinstance(final, dict):
        fail(f"{code}: final evaluation missing")

    if final.get("evaluation_status") != "ok":
        fail(f"{code}: not an official evaluation")

    breakdown = final.get("score_breakdown")
    if not isinstance(breakdown, dict):
        fail(f"{code}: score breakdown missing")

    for key, (section_name, score_name) in SECTIONS.items():
        section = row.get(section_name)

        if not isinstance(section, dict):
            fail(f"{code}: {section_name} missing")

        if section.get("evaluation_status") != "ok":
            fail(f"{code}: {section_name} not ok")

        value = section.get(score_name)
        recorded = breakdown.get(key)

        if not number(value, 0, LIMITS[key]):
            fail(f"{code}: invalid {score_name}")

        if not number(recorded, 0, LIMITS[key]):
            fail(f"{code}: invalid breakdown {key}")

        if abs(value - recorded) > 0.11:
            fail(f"{code}: {key} score mismatch")

    sector = row["sector_evaluation"]
    sector_date = sector.get(
        "sector_base_date", sector.get("base_date")
    )
    check_date(
        sector_date,
        os.environ["BASE_DATE"],
        f"{code} sector",
    )

    if sector.get("sector_count") != 18:
        fail(f"{code}: sector count != 18")

    market = row["market_evaluation"]
    futures = market.get("futures")

    if not isinstance(futures, dict):
        fail(f"{code}: futures missing")

    usable = [
        item for item in futures.values()
        if isinstance(item, dict)
        and item.get("usable") is True
        and item.get("status") in ("ok", "closed")
        and number(item.get("change_pct"), -1000, 1000)
    ]
    if not usable:
        fail(f"{code}: verified futures missing")

    score = final.get("final_score")
    rank = final.get("final_rank")

    if not number(score, 0, 100):
        fail(f"{code}: invalid final score")

    if rank not in ("S", "A", "B", "C", "D", "E"):
        fail(f"{code}: invalid final rank")

    hits = row.get("hit_count")
    if (
        isinstance(hits, bool)
        or not isinstance(hits, int)
        or not 1 <= hits <= 4
    ):
        fail(f"{code}: invalid hit_count")

    bonus = final.get("multi_strategy_bonus", 0)
    if not number(bonus, 0, 3) or bonus > hits - 1:
        fail(f"{code}: invalid multi-strategy bonus")

    expected_score = min(
        100, sum(breakdown.values()) + bonus
    )
    if abs(score - expected_score) > 0.11:
        fail(f"{code}: final score mismatch")

    expected_rank = rank_from_score(score)
    safety = final.get("safety", {})
    if not isinstance(safety, dict):
        fail(f"{code}: safety missing")

    metrics = row.get("metrics") or {}
    if not isinstance(metrics, dict):
        fail(f"{code}: metrics invalid")

    if (
        safety.get("data_quality_warning") is True
        or metrics.get("data_quality_status") == "warning"
        or sector.get("data_quality_status") == "warning"
    ):
        expected_rank = cap_rank(expected_rank, "B")

    if safety.get("strategy_negated") is True:
        expected_rank = cap_rank(expected_rank, "C")

    if rank != expected_rank:
        fail(f"{code}: rank mismatch {rank} != {expected_rank}")


def validate_official(data, expected):
    rows = check_common(data, expected)

    if data.get("official_publication_allowed") is False:
        fail("official publication explicitly prohibited")

    if not rows:
        fail("official ranking has zero rows")

    for row in rows:
        check_official_row(row)

    print(
        "OFFICIAL VALIDATION PASSED:",
        f"base_date={expected}",
        f"stocks={len(rows)}",
        flush=True,
    )


def validate_diagnostic(data, expected):
    rows = check_common(data, expected)

    if data.get("official_publication_allowed") is not False:
        fail("diagnostic must prohibit official publication")

    if data.get("evaluation_status") != "incomplete":
        fail("diagnostic evaluation_status invalid")

    invalid = data.get("invalid_stocks")
    if not isinstance(invalid, list):
        fail("invalid_stocks missing")

    count = data.get("incomplete_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(invalid)
    ):
        fail("incomplete_count mismatch")

    invalid_codes = set()

    for item in invalid:
        if not isinstance(item, dict):
            fail("invalid_stocks item invalid")

        code = str(item.get("code", "")).strip()
        if not code or code in invalid_codes:
            fail("invalid_stocks code missing or duplicated")

        if not any(
            item.get(key)
            for key in (
                "reason", "component_reason",
                "missing_components", "missing_reasons"
            )
        ):
            fail(f"{code}: missing reason absent")

        invalid_codes.add(code)

    actual_incomplete = set()

    for row in rows:
        code = str(row["code"])
        final = row.get("final_evaluation")

        if not isinstance(final, dict):
            fail(f"{code}: final evaluation missing")

        incomplete = (
            final.get("evaluation_status") != "ok"
            or final.get("final_score") is None
            or final.get("final_rank") is None
        )

        if incomplete:
            actual_incomplete.add(code)

            for field in (
                "final_score", "final_rank",
                "uncapped_rank", "base_score"
            ):
                if final.get(field) is not None:
                    fail(f"{code}: {field} must be null")

            # 欠損時の暫定点数を正式結果として認めない
            if final.get("evaluation_status") == "ok":
                fail(f"{code}: incomplete status marked ok")

    if invalid_codes != actual_incomplete:
        fail("invalid_stocks and incomplete rows mismatch")

    if count != len(actual_incomplete):
        fail("incomplete_count does not match rows")

    print(
        "DIAGNOSTIC VALIDATION PASSED:",
        f"base_date={expected}",
        f"hits={len(rows)}",
        f"incomplete={count}",
        flush=True,
    )
    print(
        "OFFICIAL PUBLICATION NOT AUTHORIZED",
        flush=True,
    )

def validate_provisional(data, expected):
    rows = check_common(data, expected)

    if not rows:
        fail("provisional ranking has zero rows")

    if data.get("publication_status") != "provisional":
        fail("publication_status must be provisional")

    if data.get("official_publication_allowed") is not False:
        fail("official publication must be prohibited")

    if data.get("max_score") != 85:
        fail("provisional max_score must be 85")

    for row in rows:
        code = str(row["code"])
        final = row.get("final_evaluation")

        if not isinstance(final, dict):
            fail(f"{code}: final evaluation missing")

        if final.get("evaluation_status") != "provisional":
            fail(f"{code}: not provisional")

        if final.get("market_excluded") is not True:
            fail(f"{code}: market exclusion missing")

        if final.get("max_score") != 85:
            fail(f"{code}: max_score must be 85")

        breakdown = final.get("score_breakdown")

        if not isinstance(breakdown, dict):
            fail(f"{code}: breakdown missing")

        if breakdown.get("market") is not None:
            fail(f"{code}: market must be null")

        market = row.get("market_evaluation")

        if not isinstance(market, dict):
            fail(f"{code}: market evaluation missing")

        if market.get("evaluation_status") == "ok":
            fail(f"{code}: usable market cannot be excluded")

        total = 0.0

        for key in (
            "strategy_fit",
            "sector",
            "technical",
            "volume_supply",
        ):
            section_name, score_name = SECTIONS[key]
            section = row.get(section_name)

            if not isinstance(section, dict):
                fail(f"{code}: {section_name} missing")

            if section.get("evaluation_status") != "ok":
                fail(f"{code}: {section_name} not ok")

            value = section.get(score_name)
            recorded = breakdown.get(key)

            if not number(value, 0, LIMITS[key]):
                fail(f"{code}: invalid {score_name}")

            if not number(recorded, 0, LIMITS[key]):
                fail(f"{code}: invalid breakdown {key}")

            if abs(value - recorded) > 0.11:
                fail(f"{code}: breakdown mismatch {key}")

            total += value

        sector = row["sector_evaluation"]

        check_date(
            sector.get("sector_base_date"),
            expected,
            f"{code} sector",
        )

        if sector.get("sector_count") != 18:
            fail(f"{code}: sector count != 18")

        hits = row.get("hit_count")

        if (
            isinstance(hits, bool)
            or not isinstance(hits, int)
            or not 1 <= hits <= 4
        ):
            fail(f"{code}: invalid hit_count")

        bonus = final.get("multi_strategy_bonus")

        if (
            not number(bonus, 0, 3)
            or bonus > hits - 1
        ):
            fail(f"{code}: invalid bonus")

        expected_total = round(
            min(85, total + bonus), 1
        )

        actual_total = final.get("final_score")

        if not number(actual_total, 0, 85):
            fail(f"{code}: invalid final_score")

        if abs(actual_total - expected_total) > 0.11:
            fail(f"{code}: total mismatch")

        expected_normalized = round(
            actual_total / 85 * 100, 1
        )

        normalized = final.get("normalized_score")

        if not number(normalized, 0, 100):
            fail(f"{code}: normalized_score invalid")

        if abs(normalized - expected_normalized) > 0.11:
            fail(f"{code}: normalized score mismatch")

        expected_rank = rank_from_score(normalized)

        safety = final.get("safety")

        if not isinstance(safety, dict):
            fail(f"{code}: safety missing")

        metrics = row.get("metrics") or {}

        if not isinstance(metrics, dict):
            fail(f"{code}: metrics invalid")

        if (
            safety.get("data_quality_warning") is True
            or metrics.get("data_quality_status") == "warning"
            or sector.get("data_quality_status") == "warning"
        ):
            expected_rank = cap_rank(expected_rank, "B")

        if safety.get("strategy_negated") is True:
            expected_rank = cap_rank(expected_rank, "C")

        if final.get("final_rank") != expected_rank:
            fail(
                f"{code}: rank mismatch "
                f"{final.get('final_rank')} != {expected_rank}"
            )

    print(
        "PROVISIONAL VALIDATION PASSED:",
        f"base_date={expected}",
        f"stocks={len(rows)}",
        "max_score=85",
        flush=True,
    )
def main():
    mode = os.getenv(
        "VALIDATION_MODE", "official"
    ).strip()

    expected = os.getenv("BASE_DATE", "").strip()

    if mode not in (
        "official",
        "provisional",
        "diagnostic",
    ):
        fail(f"unknown validation mode: {mode}")

    if not expected:
        fail("BASE_DATE environment variable missing")

    check_date(expected, expected, "requested base date")

    if mode == "official":
        validate_official(
            read_file(OFFICIAL_FILE),
            expected,
        )

    elif mode == "provisional":
        validate_provisional(
            read_file(
                Path(
                    "output/"
                    "strategy_hits_provisional_latest.json"
                )
            ),
            expected,
        )

    else:
        validate_diagnostic(
            read_file(DIAGNOSTIC_FILE),
            expected,
        )


if __name__ == "__main__":
    main()
