
"""
screener.py の静的安全チェック。

実データ取得なし。
GitHub Actions の自動実行を待たずに実行可能。
"""

import ast
from pathlib import Path


SOURCE = Path("screener.py")


def main():
    if not SOURCE.exists():
        raise RuntimeError("screener.py not found")

    code = SOURCE.read_text(encoding="utf-8")

    # 1. Python構文チェック
    tree = ast.parse(code, filename=str(SOURCE))
    print("PASS: Python syntax")

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    # 2. 必須関数の存在確認
    required = [
        "calculate_metrics",
        "score_market_condition_15",
        "load_sector_evaluation_data",
        "score_final_evaluation_100",
        "attach_final_evaluations",
        "main",
    ]

    missing = [
        name
        for name in required
        if name not in functions
    ]

    if missing:
        raise RuntimeError(
            f"Missing functions: {missing}"
        )

    print("PASS: Required functions")

    # 3. 地合い採点の既知の仕様不一致
    market_function = functions[
        "score_market_condition_15"
    ]

    assignments = [
        node
        for node in ast.walk(market_function)
        if isinstance(node, ast.Assign)
    ]

    osaka_forced_false = any(
        isinstance(node.value, ast.Constant)
        and node.value.value is False
        and any(
            isinstance(target, ast.Name)
            and target.id == "osaka_usable"
            for target in node.targets
        )
        for node in assignments
    )

    if osaka_forced_false:
        print(
            "FAIL: Osaka futures is forcibly "
            "marked unusable"
        )
    else:
        print("PASS: Osaka futures flag")

    # 4. 地合い評価がCME専用か確認
    cme_only = any(
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cme_score"
        and any(
            isinstance(target, ast.Name)
            and target.id == "futures_score"
            for target in node.targets
        )
        for node in assignments
    )

    if cme_only:
        print(
            "FAIL: Futures score uses CME only"
        )
    else:
        print("PASS: Futures score structure")

    if osaka_forced_false or cme_only:
        raise RuntimeError(
            "Market scoring implementation "
            "does not match Osaka/CME specification"
        )

    print("ALL STATIC CHECKS PASSED")


if __name__ == "__main__":
    main()
