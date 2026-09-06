"""
市場データ取得モジュールの設定。

ここに取得対象の市場指標を追加していく。

設計方針:
- 指標ごとの設定をここで一元管理する
- 取得処理そのものは別ファイルに分離する
- 将来、為替・米国指数・金利・VIX・商品などを追加できる形にする
"""


MARKET_DATA_ITEMS = [
    {
        "key": "nikkei225_futures",
        "name": "日経225先物",
        "category": "futures",

        # 主取得元
        "primary": {
            "source": "yfinance",
            "symbol": "NIY=F",
        },

        # 主取得元が失敗した場合に使う取得元。
        # 最初は未設定。
        "fallback": None,

        # データ鮮度判定用。
        # 取得値がこの時間より古い場合は
        # 当日値として正常公開しない。
        "max_age_minutes": 180,
    },
]


REQUIRED_OUTPUT_FIELDS = [
    "key",
    "name",
    "category",
    "symbol",
    "source",
    "value",
    "change",
    "change_pct",
    "as_of",
    "status",
]