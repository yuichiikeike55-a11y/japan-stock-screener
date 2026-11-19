
import json
import os
import re
from pathlib import Path

RANKING = Path("output/strategy_hits_latest.json")
STOCK_DIR = Path("output/stocks")


def stop(message):
    raise SystemExit(f"[STOCK EXPORT STOP] {message}")


def main():
    if not RANKING.is_file():
        stop("正式ランキングJSONがありません")

    data = json.loads(RANKING.read_text(encoding="utf-8"))
    base_date = data.get("base_date")

    if not isinstance(base_date, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", base_date
    ):
        stop("基準日が不正です")

    expected = os.getenv("BASE_DATE")
    if expected and expected != base_date:
        stop("指定基準日と正式ランキングが不一致です")

    if (
        data.get("publication_status") != "official"
        or data.get("evaluation_status") != "official"
        or data.get("official_publication_allowed") is not True
    ):
        stop("正式公開データではありません")

    results = data.get("results")
    if not isinstance(results, list) or not results:
        stop("銘柄データがありません")

    if data.get("unique_stock_count") != len(results):
        stop("銘柄件数が一致しません")

    output = {}

    for stock in results:
        if not isinstance(stock, dict):
            stop("銘柄レコードが不正です")

        code = str(stock.get("code", ""))
        metrics = stock.get("metrics")
        evaluation = stock.get("final_evaluation")

        if not re.fullmatch(r"\d{4}", code):
            stop(f"銘柄コード不正: {code}")

        if code in output:
            stop(f"銘柄コード重複: {code}")

        if stock.get("base_date") != base_date:
            stop(f"銘柄基準日不一致: {code}")

        if not isinstance(metrics, dict):
            stop(f"個別指標欠損: {code}")

        if (
            metrics.get("base_date") != base_date
            or str(metrics.get("code")) != code
        ):
            stop(f"個別指標基準日・コード不一致: {code}")

        if not isinstance(evaluation, dict):
            stop(f"最終評価欠損: {code}")

        if (
            evaluation.get("evaluation_status") != "ok"
            or evaluation.get("publication_status") != "official"
            or evaluation.get("final_score") is None
            or not evaluation.get("final_rank")
        ):
            stop(f"最終評価不正: {code}")

        output[code] = stock

    STOCK_DIR.mkdir(parents=True, exist_ok=True)

    for code, stock in output.items():
        path = STOCK_DIR / f"{code}.json"
        temporary = STOCK_DIR / f".{code}.json.tmp"

        temporary.write_text(
            json.dumps(stock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    print(
        f"[STOCK JSON EXPORTED] "
        f"base_date={base_date} count={len(output)}"
    )


if __name__ == "__main__":
    main()
