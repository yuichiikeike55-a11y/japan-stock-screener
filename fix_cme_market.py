
from pathlib import Path
import ast
import re

TARGET = Path("screener.py")
BACKUP = Path("screener.py.before_cme_fix.bak")

source = TARGET.read_text(encoding="utf-8")
tree = ast.parse(source)

functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "score_market_condition_15"
]

if len(functions) != 1:
    raise SystemExit(
        "STOP: 地合い評価関数を一意に特定できません"
    )

start_marker = "    # 7. 大阪先物 最大4点"
end_marker = "    # 9. 合計 15点"

if source.count(start_marker) != 1:
    raise SystemExit("STOP: 旧採点開始位置が不一致")

if source.count(end_marker) != 1:
    raise SystemExit("STOP: 旧採点終了位置が不一致")

start = source.index(start_marker)
end = source.index(end_marker)

if start >= end:
    raise SystemExit("STOP: 採点範囲が不正")

old = source[start:end]

for required in (
    "osaka_score = 0",
    "cme_score = 0",
    "osaka_usable",
    "cme_usable",
    "futures_score = (",
):
    if required not in old:
        raise SystemExit(
            f"STOP: 想定外の採点構造: {required}"
        )

# CMEが利用できなければ停止
condition = re.compile(
    r"(?m)^    if \(\s*\n"
    r"        not osaka_usable\s*\n"
    r"        and not cme_usable\s*\n"
    r"    \):"
)

updated, count = condition.subn(
    "    if not cme_usable:",
    source,
)

if count != 1:
    raise SystemExit(
        "STOP: CME必須条件を特定できません"
    )

start = updated.index(start_marker)
end = updated.index(end_marker)

replacement = '''    # --------------------------------------------------------
    # 7. CME先物専用 最大6点
    # --------------------------------------------------------

    osaka_score = 0
    osaka_change_pct = None
    osaka_usable = False

    cme_change_pct = _num(cme, "change_pct")

    if cme_change_pct is None:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "cme_change_pct_missing",
            "market_internal_score": internal_score,
        }

    if cme_change_pct >= 1.0:
        cme_score = 6
    elif cme_change_pct >= 0.5:
        cme_score = 5
    elif cme_change_pct >= 0.2:
        cme_score = 4
    elif cme_change_pct >= 0.0:
        cme_score = 3
    elif cme_change_pct >= -0.5:
        cme_score = 2
    elif cme_change_pct >= -1.0:
        cme_score = 1
    else:
        cme_score = 0

    futures_score = cme_score

    # --------------------------------------------------------
'''

updated = (
    updated[:start]
    + replacement
    + updated[end:]
)

# ログ表示の旧配点を変更
old_display = '''        "osaka:",
        market_breakdown.get(
            "osaka_futures"
        ),
        "/4",
        "cme:",
        market_breakdown.get(
            "cme_futures"
        ),
        "/2",'''

new_display = '''        "cme:",
        market_breakdown.get(
            "cme_futures"
        ),
        "/6",'''

if updated.count(old_display) != 1:
    raise SystemExit(
        "STOP: 地合いログ表示の構造が不一致"
    )

updated = updated.replace(
    old_display,
    new_display,
    1,
)

# CME基準日と日本株基準日の一致を検証
anchor = '''    if not cme_usable:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "futures_data_unavailable",
            "market_internal_score": internal_score,
        }'''

if updated.count(anchor) != 1:
    raise SystemExit(
        "STOP: CME停止条件が想定外です"
    )

date_check = '''    if not cme_usable:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "cme_futures_unavailable",
            "market_internal_score": internal_score,
        }

    expected_dates = set(
        metrics["base_date"].dropna().astype(str)
    )

    if len(expected_dates) != 1:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "stock_base_date_invalid",
        }

    expected_date = next(iter(expected_dates))

    if cme.get("evaluation_base_date") != expected_date:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "cme_base_date_mismatch",
        }'''

updated = updated.replace(
    anchor,
    date_check,
    1,
)

# 構文確認
ast.parse(updated, filename=str(TARGET))

# 旧ファイルを保護
if BACKUP.exists():
    raise SystemExit(
        "STOP: バックアップが既に存在します"
    )

BACKUP.write_text(source, encoding="utf-8")
TARGET.write_text(updated, encoding="utf-8")

print("CME専用6点への修正を適用しました")
print("市場内部: 最大9点")
print("CME先物: 最大6点")
print("大阪先物: 採点対象外")
print("Python構文: OK")
print("バックアップ:", BACKUP)
