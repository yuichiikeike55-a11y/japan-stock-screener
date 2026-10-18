
from pathlib import Path
import ast
import re
import shutil

TARGET = Path("screener.py")
BACKUP = Path("screener.py.before_patch")

if not TARGET.is_file():
    raise SystemExit("screener.py が見つかりません")

source = TARGET.read_text(encoding="utf-8")
tree = ast.parse(source)

functions = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

required = [
    "score_market_condition_15",
    "load_sector_evaluation_data",
    "main",
]

missing = [name for name in required if name not in functions]
if missing:
    raise SystemExit(f"必要な関数がありません: {missing}")

if "CME_ONLY_MARKET_PATCH_V1" in source:
    raise SystemExit("この修正は適用済みです")

# 1. 地合い評価をCME単独・15点満点に変更
#    市場内部9点 + CME6点
#    元の内部指標の算出式は維持する。

market = functions["score_market_condition_15"]
market_text = ast.get_source_segment(source, market)

start_marker = "    # 5. 大阪・CMEを取得"
start = market_text.find(start_marker)

if start < 0:
    raise SystemExit("地合い評価の旧コードが見つかりません")

# セクション5以降は新しいCME専用の処理に置換
market_text = market_text[:start] + '''
    # CME_ONLY_MARKET_PATCH_V1
    lookup = {
        row.get("key"): row
        for row in results
        if isinstance(row, dict)
    }
    cme = lookup.get("nikkei225_futures_cme")

    if not cme or cme.get("status") != "ok":
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "cme_futures_unavailable",
            "market_internal_score": internal_score,
        }

    change_pct = _num(cme, "change_pct")
    if change_pct is None:
        return {
            "market_score": None,
            "evaluation_status": "stopped",
            "stop_reason": "cme_change_pct_missing",
            "market_internal_score": internal_score,
        }

    if change_pct >= 1.0:
        cme_score = 6
    elif change_pct >= 0.5:
        cme_score = 5
    elif change_pct >= 0.3:
        cme_score = 4
    elif change_pct >= 0.0:
        cme_score = 3
    elif change_pct >= -0.5:
        cme_score = 2
    elif change_pct >= -1.0:
        cme_score = 1
    else:
        cme_score = 0

    total = max(0, min(15, int(internal_score + cme_score)))

    if total >= 12:
        condition = "strong"
    elif total >= 8:
        condition = "neutral"
    else:
        condition = "weak"

    return {
        "market_score": total,
        "market_condition": condition,
        "evaluation_status": "ok",
        "stop_reason": None,
        "market_internal_score": internal_score,
        "market_score_breakdown": {
            "internal": internal_score,
            "above_ma25": above_ma25_score,
            "ma25_up": ma25_up_score,
            "advancing": advancing_score,
            "futures": cme_score,
            "osaka_futures": 0,
            "cme_futures": cme_score,
        },
        "market_internal": {
            "above_ma25_ratio": float(above_ma25_ratio),
            "ma25_up_ratio": float(ma25_up_ratio),
            "advancing_ratio": float(advancing_ratio),
        },
        "market_futures": {
            "osaka": None,
            "cme": cme,
        },
    }
'''

# 2. 置換は末尾から行い、行番号のズレを防止
lines = source.splitlines(keepends=True)
begin = market.lineno - 1
end = market.end_lineno
lines[begin:end] = [market_text.rstrip() + "\n\n"]
source = "".join(lines)

# 3. main開始時にmetrics空の安全弁を追加
tree = ast.parse(source)
main = next(
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name == "main"
)

# metricsが生成された直後に停止するよう、
# code列参照の直前にも保護を入れる。
pattern = re.compile(
    r"(?m)^(?P<indent>[ \\t]*)"
    r"(?P<expr>metrics\\[['\\\"]code['\\\"]\\]\\.isin\\(debug_codes\\))"
)

def protect(match):
    indent = match.group("indent")
    expression = match.group("expr")
    return (
        "metrics['code'].isin(debug_codes)"
        if False else expression
    )

# code列がない場合は明確な例外に変換する。
# 空データのまま結果公開へ進めない。
guard = '''
    if metrics is None or metrics.empty or "code" not in metrics.columns:
        raise RuntimeError(
            "Screening stopped: metrics is empty or code column missing. "
            "No results will be published."
        )
'''

# main内で最初のdebug_codes参照を探す
tree = ast.parse(source)
main = next(
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name == "main"
)

main_lines = source.splitlines(keepends=True)
insert_at = None

for index in range(main.lineno - 1, main.end_lineno):
    if "metrics['code'].isin(debug_codes)" in main_lines[index] or \
       'metrics["code"].isin(debug_codes)' in main_lines[index]:
        insert_at = index
        break

if insert_at is None:
    raise SystemExit(
        "metrics['code'].isin(debug_codes) が見つかりません。"
        "安全のため変更を保存しません。"
    )

main_lines.insert(insert_at, guard + "\n")
source = "".join(main_lines)

# 4. セクター日付不一致は既存の停止判定を維持
#    日付の自動書き換えは行わない。
#    追加で正常データがないときの公開を防ぐ。

# 5. 構文検証後に保存
ast.parse(source)

if BACKUP.exists():
    raise SystemExit(
        "バックアップが既にあります。"
        "誤上書き防止のため停止します。"
    )

shutil.copy2(TARGET, BACKUP)
TARGET.write_text(source, encoding="utf-8")

print("PATCH COMPLETE")
print("Backup:", BACKUP)
print("Updated:", TARGET)
print("Market: internal 9 + CME 6")
print("Osaka futures: optional")
print("Empty metrics: fail closed")
print("Sector date mismatch: existing stop retained")
