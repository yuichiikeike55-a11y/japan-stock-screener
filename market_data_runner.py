
"""
無料運用版：CME先物のみ取得。

大阪先物は必須条件から除外。
取得失敗・鮮度不足なら保存せず停止。

出力:
    output/market_data.json
    output/market_data_history/market_data_YYYY-MM-DD.json
"""

import json
import os

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

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


JST = ZoneInfo("Asia/Tokyo")

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "market_data.json"

HISTORY_DIR = (
    OUTPUT_DIR / "market_data_history"
)


def main():
    now_jst = datetime.now(JST)

    base_date_text = os.getenv(
        "BASE_DATE", ""
    ).strip()

    base_date = (
        datetime.strptime(
            base_date_text,
            "%Y-%m-%d",
        ).date()
        if base_date_text
        else now_jst.date()
    )

    if base_date != now_jst.date():
        raise RuntimeError(
            "Historical/future BASE_DATE "
            "is not supported without a "
            "verified saved snapshot. "
            f"BASE_DATE={base_date} "
            f"today={now_jst.date()}"
        )

    evaluation_cutoff = datetime.combine(
        base_date,
        time(20, 30),
        tzinfo=JST,
    )

    effective_cutoff = min(
        now_jst,
        evaluation_cutoff,
    )

    # =====================================
    # CME先物のみ取得
    # =====================================

    symbol = "NKD=F"

    print(
        "Fetching CME futures:",
        symbol,
    )

    hourly = fetch_yfinance(symbol)
    daily = fetch_yfinance_daily(symbol)

    normalized = normalize_yfinance(
        symbol,
        hourly,
        daily,
        cutoff=effective_cutoff,
    )

    validated = validate_freshness(
        normalized,
        180,
        now=effective_cutoff,
    )

    print(
        "CME freshness:",
        validated.get("status"),
        validated.get("as_of"),
        validated.get("age_minutes"),
    )

    if validated.get("status") != "ok":
        raise RuntimeError(
            "CME futures unavailable or stale: "
            f"{validated.get('reason')}"
        )

    as_of_jst = datetime.fromisoformat(
        validated["as_of"]
    ).astimezone(JST)

    if as_of_jst > effective_cutoff:
        raise RuntimeError(
            "CME observation after cutoff"
        )

    # =====================================
    # 正式出力
    # =====================================

    result = {
        "key": "nikkei225_futures_cme",
        "name": "日経225先物（CME）",
        "category": "futures",
        **validated,
        "as_of_jst": as_of_jst.isoformat(),
        "evaluation_base_date": (
            base_date.isoformat()
        ),
        "evaluation_cutoff_jst": (
            evaluation_cutoff.isoformat()
        ),
    }

    output_data = {
        "results": [result]
    }

    snapshot_file = (
        HISTORY_DIR
        / (
            "market_data_"
            f"{base_date.isoformat()}.json"
        )
    )

    # =====================================
    # 古いデータで上書きしない
    # =====================================

    if snapshot_file.exists():
        with open(
            snapshot_file,
            encoding="utf-8",
        ) as f:
            existing = json.load(f)

        previous_results = {
            item["key"]: item
            for item in existing.get(
                "results", []
            )
        }

        previous = previous_results.get(
            "nikkei225_futures_cme"
        )

        if previous is not None:
            previous_time = (
                datetime.fromisoformat(
                    previous["as_of"]
                ).astimezone(JST)
            )

            if as_of_jst < previous_time:
                raise RuntimeError(
                    "Existing CME snapshot "
                    "is newer. Refusing overwrite."
                )

    # =====================================
    # 保存
    # =====================================

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoded = json.dumps(
        output_data,
        ensure_ascii=False,
        indent=2,
    )

    snapshot_tmp = (
        snapshot_file.with_suffix(
            ".json.tmp"
        )
    )

    output_tmp = (
        OUTPUT_FILE.with_suffix(
            ".json.tmp"
        )
    )

    snapshot_tmp.write_text(
        encoded,
        encoding="utf-8",
    )

    output_tmp.write_text(
        encoded,
        encoding="utf-8",
    )

    os.replace(
        snapshot_tmp,
        snapshot_file,
    )

    os.replace(
        output_tmp,
        OUTPUT_FILE,
    )

    print(
        "Saved CME snapshot:",
        snapshot_file,
    )

    print(
        "Saved market data:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
