
from pathlib import Path
import ast
import sys

TARGET = Path("screener.py")

if not TARGET.is_file():
    sys.exit("STOP: screener.py がありません")

source = TARGET.read_text(encoding="utf-8")
original = source

# 1. metrics が空なら KeyError の前に停止
debug_anchor = "metrics['code'].isin(debug_codes)"

if debug_anchor not in source:
    sys.exit(
        "STOP: metrics['code'] の位置が見つかりません。"
        "変更せず停止します。"
    )

lines = source.splitlines(keepends=True)

if "STOP: stock metrics empty or code missing" not in source:
    for index, line in enumerate(lines):
        if debug_anchor in line:
            indent = line[:len(line) - len(line.lstrip())]
            guard = (
                f"{indent}if metrics is None or metrics.empty "
                f"or 'code' not in metrics.columns:\n"
                f"{indent}    raise RuntimeError(\n"
                f"{indent}        'STOP: stock metrics empty or code missing'\n"
                f"{indent}    )\n"
            )
            lines.insert(index, guard)
            break

source = "".join(lines)

# 2. 地合い評価停止時は後続処理へ進ませない
market_anchor = """    market_evaluation = (
        score_market_condition_15(
            metrics
        )
    )
"""

market_guard = """
    if market_evaluation.get("evaluation_status") != "ok":
        raise RuntimeError(
            "STOP: market evaluation failed: "
            + str(market_evaluation.get("stop_reason"))
        )
"""

if market_guard.strip() not in source:
    if source.count(market_anchor) != 1:
        sys.exit(
            "STOP: 地合い評価の挿入位置が一意ではありません。"
            "変更せず停止します。"
        )
    source = source.replace(
        market_anchor,
        market_anchor + market_guard,
        1,
    )

# 3. Python構文を検証
try:
    ast.parse(source, filename=str(TARGET))
except SyntaxError as exc:
    sys.exit(f"STOP: 構文エラー: {exc}")

# 4. 問題がなければバックアップして保存
backup = Path("screener.py.before_safety_patch.bak")

if source == original:
    print("変更不要：安全停止処理は適用済みです")
else:
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    TARGET.write_text(source, encoding="utf-8")
    print("OK: screener.py の安全停止処理を更新しました")
    print("Backup:", backup)

print("Python syntax: OK")
