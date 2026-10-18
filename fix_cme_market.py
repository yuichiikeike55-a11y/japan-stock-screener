
from pathlib import Path
import ast
import shutil

TARGET = Path("screener.py")
BACKUP = Path("screener.py.before_cme_fix.bak")

source = TARGET.read_text(encoding="utf-8")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"STOP: {label}: expected 1 match, found {count}"
        )
    return text.replace(old, new, 1)

# 1. CMEを必須にする
old_condition = """    if (
        not osaka_usable
        and not cme_usable
    ):"""

new_condition = """    if not cme_usable:"""

updated = replace_once(
    source,
    old_condition,
    new_condition,
    "CME required condition",
)

# 2. 大阪4点＋CME2点をCME6点へ変更
start_marker = "    # 7. 大阪先物 最大4点"
end_marker = "    # 9. 合計 15点"

if updated.count(start_marker) != 1:
    raise RuntimeError("STOP: Osaka scoring marker mismatch")

if updated.count(end_marker) != 1:
    raise RuntimeError("STOP: Total scoring marker mismatch")

start = updated.index(start_marker)
end = updated.index(end_marker)

if end <= start:
    raise RuntimeError("STOP: Invalid scoring order")

old_section = updated[start:end]

required = (
    "osaka_score = 0",
    "cme_score = 0",
    "futures_score = (",
)

if not all(item in old_section for item in required):
    raise RuntimeError("STOP: Unexpected scoring structure")

replacement = """    # --------------------------------------------------------
    # 7. CME futures only: maximum 6 points
    # --------------------------------------------------------

    osaka_score = 0
    osaka_change_pct = None

    cme_change_pct = _num(
        cme,
        "change_pct",
    )

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
"""

updated = (
    updated[:start]
    + replacement
    + updated[end:]
)

# 3. ログ表示の配点も変更
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

updated = replace_once(
    updated,
    old_display,
    new_display,
    "Market score display",
)

# 4. 構文検証
ast.parse(updated, filename=str(TARGET))

# 5. バックアップと書き込み
if BACKUP.exists():
    raise RuntimeError(
        "STOP: Backup already exists; refusing overwrite"
    )

shutil.copy2(TARGET, BACKUP)
TARGET.write_text(updated, encoding="utf-8")

print("CME-only market scoring patch applied")
print("Internal market: 9 points")
print("CME futures: 6 points")
print("Osaka futures: excluded")
print("Python syntax: OK")
print("Backup:", BACKUP)
